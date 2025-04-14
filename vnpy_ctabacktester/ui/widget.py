import csv
import subprocess
from datetime import datetime, timedelta
from copy import copy
from typing import List, Tuple
from lightweight_charts.widgets import QtChart
import random
from uuid import uuid1
from qtpy.QtWidgets import QVBoxLayout

import numpy as np
import pyqtgraph as pg
from pandas import DataFrame
from copy import deepcopy

from vnpy.trader.constant import Interval, Direction, Exchange, Dividend
from vnpy.trader.engine import MainEngine, BaseEngine
from vnpy.trader.ui import QtCore, QtWidgets, QtGui
from vnpy.trader.ui.widget import BaseMonitor, BaseCell, DirectionCell, EnumCell, PnlCell
from vnpy.event import Event, EventEngine
from vnpy.chart import ChartWidget, CandleItem, VolumeItem
from vnpy.trader.utility import load_json, save_json
from vnpy.trader.object import BarData, TradeData, OrderData, TickData
from vnpy.trader.database import DB_TZ
from vnpy_ctastrategy.backtesting import DailyResult
from vnpy_ctastrategy.base import IndicatorStore, IndicatorConfig, IndicatorMarkItem

from ..locale import _
from ..engine import (
    APP_NAME,
    EVENT_BACKTESTER_LOG,
    EVENT_BACKTESTER_BACKTESTING_FINISHED,
    EVENT_BACKTESTER_OPTIMIZATION_FINISHED,
    OptimizationSetting
)


TICK_BAR_MODE = {
    '1sec': 1,
    '2sec': 2,
    '3sec': 3,
    '4sec': 4,
    '5sec': 5,
    '6sec': 6,
    '10sec': 10,
    '12sec': 12,
    '15sec': 15,
    '20sec': 20,
    '30sec': 30
}

DIVIDEND_MODE = [e.value for e in Dividend]


class BacktesterManager(QtWidgets.QWidget):
    """"""

    setting_filename: str = "cta_backtester_setting.json"

    signal_log: QtCore.Signal = QtCore.Signal(Event)
    signal_backtesting_finished: QtCore.Signal = QtCore.Signal(Event)
    signal_optimization_finished: QtCore.Signal = QtCore.Signal(Event)

    def __init__(self, main_engine: MainEngine, event_engine: EventEngine) -> None:
        """"""
        super().__init__()

        self.main_engine: MainEngine = main_engine
        self.event_engine: EventEngine = event_engine

        self.backtester_engine: BaseEngine = main_engine.get_engine(APP_NAME)
        self.class_names: list = []
        self.settings: dict = {}

        self.target_display: str = ""

        self.init_ui()
        self.register_event()
        self.backtester_engine.init_engine()
        self.init_strategy_settings()
        self.load_backtesting_setting()

    def init_strategy_settings(self) -> None:
        """"""
        self.class_names = self.backtester_engine.get_strategy_class_names()
        self.class_names.sort()

        for class_name in self.class_names:
            setting: dict = self.backtester_engine.get_default_setting(class_name)
            self.settings[class_name] = setting

        self.class_combo.addItems(self.class_names)

    def init_ui(self) -> None:
        """"""
        self.setWindowTitle(_("CTA回测"))

        # Setting Part
        self.class_combo: QtWidgets.QComboBox = QtWidgets.QComboBox()

        self.symbol_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("IF88.CFFEX")

        self.interval_combo: QtWidgets.QComboBox = QtWidgets.QComboBox()
        for interval in Interval:
            self.interval_combo.addItem(interval.value)

        self.tick_bar_mode_combo: QtWidgets.QComboBox = QtWidgets.QComboBox()
        for mode in TICK_BAR_MODE:
            self.tick_bar_mode_combo.addItem(mode)

        enable_tick_combo_func = lambda: self.tick_bar_mode_combo.setEnabled(self.interval_combo.currentText() == Interval.TICK.value)
        self.interval_combo.currentTextChanged.connect(enable_tick_combo_func)

        self.dividend_combo: QtWidgets.QComboBox = QtWidgets.QComboBox()
        for mode in DIVIDEND_MODE:
            self.dividend_combo.addItem(mode)

        end_dt: datetime = datetime.now()
        start_dt: datetime = end_dt - timedelta(days=3 * 365)

        self.start_date_edit: QtWidgets.QDateEdit = QtWidgets.QDateEdit(
            QtCore.QDate(
                start_dt.year,
                start_dt.month,
                start_dt.day
            )
        )
        self.end_date_edit: QtWidgets.QDateEdit = QtWidgets.QDateEdit(
            QtCore.QDate.currentDate()
        )

        self.rate_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("0.000025")
        self.slippage_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("0.2")
        self.size_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("300")
        self.pricetick_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("0.2")
        self.capital_line: QtWidgets.QLineEdit = QtWidgets.QLineEdit("1000000")
        self.ban_short_box: QtWidgets.QCheckBox = QtWidgets.QCheckBox(_("禁止卖空"))
        self.trade_on_close_price_box: QtWidgets.QCheckBox = QtWidgets.QCheckBox(_("收盘价撮合"))

        backtesting_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("开始回测"))
        backtesting_button.clicked.connect(self.start_backtesting)

        optimization_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("参数优化"))
        optimization_button.clicked.connect(self.start_optimization)

        self.result_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("优化结果"))
        self.result_button.clicked.connect(self.show_optimization_result)
        self.result_button.setEnabled(False)

        downloading_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("下载数据"))
        downloading_button.clicked.connect(self.start_downloading)

        self.order_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("委托记录"))
        self.order_button.clicked.connect(self.show_backtesting_orders)
        self.order_button.setEnabled(False)

        self.trade_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("成交记录"))
        self.trade_button.clicked.connect(self.show_backtesting_trades)
        self.trade_button.setEnabled(False)

        self.daily_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("每日盈亏"))
        self.daily_button.clicked.connect(self.show_daily_results)
        self.daily_button.setEnabled(False)

        self.candle_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("K线图表"))
        self.candle_button.clicked.connect(self.show_candle_chart)
        self.candle_button.setEnabled(False)

        edit_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("代码编辑"))
        edit_button.clicked.connect(self.edit_strategy_code)

        reload_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("策略重载"))
        reload_button.clicked.connect(self.reload_strategy_class)

        for button in [
            backtesting_button,
            optimization_button,
            downloading_button,
            self.result_button,
            self.order_button,
            self.trade_button,
            self.daily_button,
            self.candle_button,
            edit_button,
            reload_button
        ]:
            button.setFixedHeight(button.sizeHint().height() * 2)

        form: QtWidgets.QFormLayout = QtWidgets.QFormLayout()
        form.addRow(_("交易策略"), self.class_combo)
        form.addRow(_("本地代码"), self.symbol_line)
        form.addRow(_("K线周期"), self.interval_combo)
        form.addRow(_("TickBar模式"),self.tick_bar_mode_combo)
        form.addRow(_("复权模式"),self.dividend_combo)
        form.addRow(_("开始日期"), self.start_date_edit)
        form.addRow(_("结束日期"), self.end_date_edit)
        form.addRow(_("手续费率"), self.rate_line)
        form.addRow(_("交易滑点"), self.slippage_line)
        form.addRow(_("合约乘数"), self.size_line)
        form.addRow(_("价格跳动"), self.pricetick_line)
        form.addRow(_("回测资金"), self.capital_line)

        flags_grid: QtWidgets.QGridLayout = QtWidgets.QGridLayout()
        flags_grid.addWidget(self.ban_short_box, 0, 0)
        flags_grid.addWidget(self.trade_on_close_price_box, 0, 1)

        result_grid: QtWidgets.QGridLayout = QtWidgets.QGridLayout()
        result_grid.addWidget(self.trade_button, 0, 0)
        result_grid.addWidget(self.order_button, 0, 1)
        result_grid.addWidget(self.daily_button, 1, 0)
        result_grid.addWidget(self.candle_button, 1, 1)

        left_vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        left_vbox.addLayout(form)
        left_vbox.addLayout(flags_grid)
        left_vbox.addWidget(backtesting_button)
        left_vbox.addWidget(downloading_button)
        left_vbox.addStretch()
        left_vbox.addLayout(result_grid)
        left_vbox.addStretch()
        left_vbox.addWidget(optimization_button)
        left_vbox.addWidget(self.result_button)
        left_vbox.addStretch()
        left_vbox.addWidget(edit_button)
        left_vbox.addWidget(reload_button)

        # Result part
        self.statistics_monitor: StatisticsMonitor = StatisticsMonitor()

        self.log_monitor: QtWidgets.QTextEdit = QtWidgets.QTextEdit()
        # 更新时自动拖动到最下面
        self.log_monitor.textChanged.connect(lambda: self.log_monitor.moveCursor(QtGui.QTextCursor.MoveOperation.End))

        self.chart: BacktesterChart = BacktesterChart()
        chart: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        chart.addWidget(self.chart)

        self.trade_dialog: BacktestingResultDialog = BacktestingResultDialog(
            self.main_engine,
            self.event_engine,
            _("回测成交记录"),
            BacktestingTradeMonitor
        )
        self.order_dialog: BacktestingResultDialog = BacktestingResultDialog(
            self.main_engine,
            self.event_engine,
            _("回测委托记录"),
            BacktestingOrderMonitor
        )
        self.daily_dialog: BacktestingResultDialog = BacktestingResultDialog(
            self.main_engine,
            self.event_engine,
            _("回测每日盈亏"),
            DailyResultMonitor
        )

        # Candle Chart
        self.candle_dialog: CandleChartDialog_v2 = CandleChartDialog_v2()

        # Layout
        middle_vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        middle_vbox.addWidget(self.statistics_monitor)
        middle_vbox.addWidget(self.log_monitor)

        left_hbox: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        left_hbox.addLayout(left_vbox)
        left_hbox.addLayout(middle_vbox)

        left_widget: QtWidgets.QWidget = QtWidgets.QWidget()
        left_widget.setLayout(left_hbox)

        right_vbox: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        right_vbox.addWidget(self.chart)

        right_widget: QtWidgets.QWidget = QtWidgets.QWidget()
        right_widget.setLayout(right_vbox)

        hbox: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox.addWidget(left_widget)
        hbox.addWidget(right_widget)
        self.setLayout(hbox)

    def load_backtesting_setting(self) -> None:
        """"""
        setting: dict = load_json(self.setting_filename)
        if not setting:
            return

        self.class_combo.setCurrentIndex(
            self.class_combo.findText(setting["class_name"])
        )

        self.symbol_line.setText(setting["vt_symbol"])

        self.interval_combo.setCurrentIndex(
            self.interval_combo.findText(setting["interval"])
        )

        tick_bar_mode: str = setting.get("tick_bar_mode", "")
        if tick_bar_mode:
            self.tick_bar_mode_combo.setCurrentIndex(
                self.tick_bar_mode_combo.findText(tick_bar_mode)
            )
            if self.interval_combo.currentText() != Interval.TICK.value:
                self.tick_bar_mode_combo.setEnabled(False)

        dividend: str = setting.get("dividend", "")
        if dividend in DIVIDEND_MODE:
            self.dividend_combo.setCurrentIndex(
                self.dividend_combo.findText(dividend)
            )

        start_str: str = setting.get("start", "")
        if start_str:
            start_dt: QtCore.QDate = QtCore.QDate.fromString(start_str, "yyyy-MM-dd")
            self.start_date_edit.setDate(start_dt)

        end_str: str = setting.get("end", "")
        if end_str:
            end_dt: QtCore.QDate = QtCore.QDate.fromString(end_str, "yyyy-MM-dd")
            self.end_date_edit.setDate(end_dt)

        self.rate_line.setText(str(setting["rate"]))
        self.slippage_line.setText(str(setting["slippage"]))
        self.size_line.setText(str(setting["size"]))
        self.pricetick_line.setText(str(setting["pricetick"]))
        self.capital_line.setText(str(setting["capital"]))
        self.ban_short_box.setChecked(bool(setting["ban_short"]))
        self.trade_on_close_price_box.setChecked(bool(setting["trade_on_close_price"]))

    def register_event(self) -> None:
        """"""
        self.signal_log.connect(self.process_log_event)
        self.signal_backtesting_finished.connect(
            self.process_backtesting_finished_event)
        self.signal_optimization_finished.connect(
            self.process_optimization_finished_event)

        self.event_engine.register(EVENT_BACKTESTER_LOG, self.signal_log.emit)
        self.event_engine.register(EVENT_BACKTESTER_BACKTESTING_FINISHED, self.signal_backtesting_finished.emit)
        self.event_engine.register(EVENT_BACKTESTER_OPTIMIZATION_FINISHED, self.signal_optimization_finished.emit)

    def process_log_event(self, event: Event) -> None:
        """"""
        msg = event.data
        self.write_log(msg)

    def write_log(self, msg) -> None:
        """"""
        timestamp: str = datetime.now().strftime("%H:%M:%S")
        msg: str = f"{timestamp}\t{msg}"
        self.log_monitor.append(msg)

    def process_backtesting_finished_event(self, event: Event) -> None:
        """"""
        statistics: dict = self.backtester_engine.get_result_statistics()
        self.statistics_monitor.set_data(statistics)

        df: DataFrame = self.backtester_engine.get_result_df()
        self.chart.set_data(df)

        self.trade_button.setEnabled(True)
        self.order_button.setEnabled(True)
        self.daily_button.setEnabled(True)

        # Tick data can not be displayed using candle chart
        interval: str = self.interval_combo.currentText()

        # if interval != Interval.TICK.value:
        self.candle_button.setEnabled(True)

    def process_optimization_finished_event(self, event: Event) -> None:
        """"""
        self.write_log(_("请点击[优化结果]按钮查看"))
        self.result_button.setEnabled(True)

    def start_backtesting(self) -> None:
        """"""
        class_name: str = self.class_combo.currentText()
        if not class_name:
            self.write_log(_("请选择要回测的策略"))
            return

        vt_symbol: str = self.symbol_line.text()
        interval: str = self.interval_combo.currentText()
        tick_bar_mode: str = self.tick_bar_mode_combo.currentText()
        dividend: str = self.dividend_combo.currentText()
        start: datetime = self.start_date_edit.dateTime().toPython()
        end: datetime = self.end_date_edit.dateTime().toPython()
        rate: float = float(self.rate_line.text())
        slippage: float = float(self.slippage_line.text())
        size: float = float(self.size_line.text())
        pricetick: float = float(self.pricetick_line.text())
        capital: float = float(self.capital_line.text())
        ban_short: bool = self.ban_short_box.isChecked()
        trade_on_close_price: bool = self.trade_on_close_price_box.isChecked()

        # Check validity of vt_symbol
        if "." not in vt_symbol:
            self.write_log(_("本地代码缺失交易所后缀，请检查"))
            return

        __, exchange_str = vt_symbol.split(".")
        if exchange_str not in Exchange.__members__:
            self.write_log(_("本地代码的交易所后缀不正确，请检查"))
            return

        # Save backtesting parameters
        backtesting_setting: dict = {
            "class_name": class_name,
            "vt_symbol": vt_symbol,
            "interval": interval,
            "tick_bar_mode": tick_bar_mode,
            "dividend": dividend,
            "start": start.strftime("%Y-%m-%d"),
            "end": end.strftime("%Y-%m-%d"),
            "rate": rate,
            "slippage": slippage,
            "size": size,
            "pricetick": pricetick,
            "capital": capital,
            "ban_short": ban_short,
            "trade_on_close_price": trade_on_close_price,
        }
        save_json(self.setting_filename, backtesting_setting)

        # Get strategy setting
        old_setting: dict = self.settings[class_name]
        dialog: BacktestingSettingEditor = BacktestingSettingEditor(class_name, old_setting)
        i: int = dialog.exec()
        if i != dialog.DialogCode.Accepted:
            return

        new_setting: dict = dialog.get_setting()
        self.settings[class_name] = new_setting

        result: bool = self.backtester_engine.start_backtesting(
            class_name,
            vt_symbol,
            interval,
            dividend,
            start,
            end,
            rate,
            slippage,
            size,
            pricetick,
            capital,
            ban_short,
            trade_on_close_price,
            new_setting
        )

        if result:
            self.statistics_monitor.clear_data()
            self.chart.clear_data()

            self.trade_button.setEnabled(False)
            self.order_button.setEnabled(False)
            self.daily_button.setEnabled(False)
            self.candle_button.setEnabled(False)

            self.trade_dialog.clear_data()
            self.order_dialog.clear_data()
            self.daily_dialog.clear_data()
            self.candle_dialog.clear_data()

    def start_optimization(self) -> None:
        """"""
        class_name: str = self.class_combo.currentText()
        vt_symbol: str = self.symbol_line.text()
        interval: str = self.interval_combo.currentText()
        dividend: str = self.dividend_combo.currentText()
        start: object = self.start_date_edit.dateTime().toPython()
        end: object = self.end_date_edit.dateTime().toPython()
        rate: float = float(self.rate_line.text())
        slippage: float = float(self.slippage_line.text())
        size: float = float(self.size_line.text())
        pricetick: float = float(self.pricetick_line.text())
        capital: float = float(self.capital_line.text())
        ban_short: bool = self.ban_short_box.isChecked()
        trade_on_close_price: bool = self.trade_on_close_price_box.isChecked()

        parameters: dict = self.settings[class_name]
        dialog: OptimizationSettingEditor = OptimizationSettingEditor(class_name, parameters)
        i: int = dialog.exec()
        if i != dialog.DialogCode.Accepted:
            return

        optimization_setting, use_ga, max_workers = dialog.get_setting()
        self.target_display: str = dialog.target_display

        self.backtester_engine.start_optimization(
            class_name,
            vt_symbol,
            interval,
            dividend,
            start,
            end,
            rate,
            slippage,
            size,
            pricetick,
            capital,
            ban_short,
            trade_on_close_price,
            optimization_setting,
            use_ga,
            max_workers
        )

        self.result_button.setEnabled(False)

    def start_downloading(self) -> None:
        """"""
        # 要求使用 datamanager 来下载数据，而不是在这里下载，使用对话框提示
        QtWidgets.QMessageBox.information(
            None, '信息', '功能已禁用\n请使用DataManager下载数据',
            QtWidgets.QMessageBox.StandardButton.Yes, QtWidgets.QMessageBox.StandardButton.Yes
        )
        return
        #

        vt_symbol: str = self.symbol_line.text()
        interval: str = self.interval_combo.currentText()
        start_date: QtCore.QDate = self.start_date_edit.date()
        end_date: QtCore.QDate = self.end_date_edit.date()

        start: datetime = datetime(
            start_date.year(),
            start_date.month(),
            start_date.day(),
        )
        start: datetime = start.replace(tzinfo=DB_TZ)

        end: datetime = datetime(
            end_date.year(),
            end_date.month(),
            end_date.day(),
            23,
            59,
            59,
        )
        end: datetime = end.replace(tzinfo=DB_TZ)

        self.backtester_engine.start_downloading(
            vt_symbol,
            interval,
            start,
            end
        )

    def show_optimization_result(self) -> None:
        """"""
        result_values: list = self.backtester_engine.get_result_values()

        dialog: OptimizationResultMonitor = OptimizationResultMonitor(
            result_values,
            self.target_display
        )
        dialog.exec_()

    def show_backtesting_trades(self) -> None:
        """"""
        if not self.trade_dialog.is_updated():
            trades: List[TradeData] = self.backtester_engine.get_all_trades()
            self.trade_dialog.update_data(trades)

        self.trade_dialog.exec_()

    def show_backtesting_orders(self) -> None:
        """"""
        if not self.order_dialog.is_updated():
            orders: List[OrderData] = self.backtester_engine.get_all_orders()
            self.order_dialog.update_data(orders)

        self.order_dialog.exec_()

    def show_daily_results(self) -> None:
        """"""
        if not self.daily_dialog.is_updated():
            results: List[DailyResult] = self.backtester_engine.get_all_daily_results()
            self.daily_dialog.update_data(results)

        self.daily_dialog.exec_()

    def show_candle_chart(self) -> None:
        """"""
        if not self.candle_dialog.is_updated():
            history: list = self.backtester_engine.get_history_data()
            self.candle_dialog.update_history(history)

            trades: List[TradeData] = self.backtester_engine.get_all_trades()
            self.candle_dialog.update_trades(trades)

            indicators: List[dict] = self.backtester_engine.get_indicators()
            self.candle_dialog.update_indicators(indicators)

            interval: str = self.interval_combo.currentText()
            if interval == Interval.TICK.value:
                self.candle_dialog.set_tick_mode(self.tick_bar_mode_combo.currentText())
            else:
                self.candle_dialog.set_tick_mode(None)

        self.candle_dialog.exec_()

    def edit_strategy_code(self) -> None:
        """"""
        class_name: str = self.class_combo.currentText()
        if not class_name:
            return

        file_path: str = self.backtester_engine.get_strategy_class_file(class_name)
        cmd: list = ["code", file_path]

        p: subprocess.CompletedProcess = subprocess.run(cmd, shell=True)
        if p.returncode:
            QtWidgets.QMessageBox.warning(
                self,
                _("启动代码编辑器失败"),
                _("请检查是否安装了Visual Studio Code，并将其路径添加到了系统全局变量中！")
            )

    def reload_strategy_class(self) -> None:
        """"""
        self.backtester_engine.reload_strategy_class()

        current_strategy_name: str = self.class_combo.currentText()

        self.class_combo.clear()
        self.init_strategy_settings()

        ix: int = self.class_combo.findText(current_strategy_name)
        self.class_combo.setCurrentIndex(ix)

    def show(self) -> None:
        """"""
        self.showMaximized()


class StatisticsMonitor(QtWidgets.QTableWidget):
    """"""
    KEY_NAME_MAP: dict = {
        "start_date": _("首个交易日"),
        "end_date": _("最后交易日"),

        "total_days": _("总交易日"),
        "profit_days": _("盈利交易日"),
        "loss_days": _("亏损交易日"),

        "capital": _("起始资金"),
        "end_balance": _("结束资金"),

        "total_return": _("总收益率"),
        "annual_return": _("年化收益"),
        "max_drawdown": _("最大回撤"),
        "max_ddpercent": _("百分比最大回撤"),
        "max_drawdown_duration": _("最大回撤天数"),

        "total_net_pnl": _("总盈亏"),
        "total_commission": _("总手续费"),
        "total_slippage": _("总滑点"),
        "total_turnover": _("总成交额"),
        "total_trade_count": _("总成交笔数"),

        "daily_net_pnl": _("日均盈亏"),
        "daily_commission": _("日均手续费"),
        "daily_slippage": _("日均滑点"),
        "daily_turnover": _("日均成交额"),
        "daily_trade_count": _("日均成交笔数"),

        "daily_return": _("日均收益率"),
        "return_std": _("收益标准差"),
        "sharpe_ratio": _("夏普比率"),
        "ewm_sharpe": _("EWM夏普"),
        "return_drawdown_ratio": _("收益回撤比")
    }

    def __init__(self) -> None:
        """"""
        super().__init__()

        self.cells: dict = {}

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        self.setRowCount(len(self.KEY_NAME_MAP))
        self.setVerticalHeaderLabels(list(self.KEY_NAME_MAP.values()))

        self.setColumnCount(1)
        self.horizontalHeader().setVisible(False)
        self.horizontalHeader().setSectionResizeMode(
            QtWidgets.QHeaderView.ResizeMode.Stretch
        )
        self.setEditTriggers(self.EditTrigger.NoEditTriggers)

        for row, key in enumerate(self.KEY_NAME_MAP.keys()):
            cell: QtWidgets.QTableWidgetItem = QtWidgets.QTableWidgetItem()
            self.setItem(row, 0, cell)
            self.cells[key] = cell

    def clear_data(self) -> None:
        """"""
        for cell in self.cells.values():
            cell.setText("")

    def set_data(self, data: dict) -> None:
        """"""
        data["capital"] = f"{data['capital']:,.2f}"
        data["end_balance"] = f"{data['end_balance']:,.2f}"
        data["total_return"] = f"{data['total_return']:,.2f}%"
        data["annual_return"] = f"{data['annual_return']:,.2f}%"
        data["max_drawdown"] = f"{data['max_drawdown']:,.2f}"
        data["max_ddpercent"] = f"{data['max_ddpercent']:,.2f}%"
        data["total_net_pnl"] = f"{data['total_net_pnl']:,.2f}"
        data["total_commission"] = f"{data['total_commission']:,.2f}"
        data["total_slippage"] = f"{data['total_slippage']:,.2f}"
        data["total_turnover"] = f"{data['total_turnover']:,.2f}"
        data["daily_net_pnl"] = f"{data['daily_net_pnl']:,.2f}"
        data["daily_commission"] = f"{data['daily_commission']:,.2f}"
        data["daily_slippage"] = f"{data['daily_slippage']:,.2f}"
        data["daily_turnover"] = f"{data['daily_turnover']:,.2f}"
        data["daily_trade_count"] = f"{data['daily_trade_count']:,.2f}"
        data["daily_return"] = f"{data['daily_return']:,.2f}%"
        data["return_std"] = f"{data['return_std']:,.2f}%"
        data["sharpe_ratio"] = f"{data['sharpe_ratio']:,.2f}"
        data["ewm_sharpe"] = f"{data['ewm_sharpe']:,.2f}"
        data["return_drawdown_ratio"] = f"{data['return_drawdown_ratio']:,.2f}"

        for key, cell in self.cells.items():
            value = data.get(key, "")
            cell.setText(str(value))


class BacktestingSettingEditor(QtWidgets.QDialog):
    """
    For creating new strategy and editing strategy parameters.
    """

    def __init__(
        self, class_name: str, parameters: dict
    ) -> None:
        """"""
        super(BacktestingSettingEditor, self).__init__()

        self.class_name: str = class_name
        self.parameters: dict = parameters
        self.edits: dict = {}

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        form: QtWidgets.QFormLayout = QtWidgets.QFormLayout()

        # Add vt_symbol and name edit if add new strategy
        self.setWindowTitle(_("策略参数配置：{}").format(self.class_name))
        button_text: str = _("确定")
        parameters: dict = self.parameters

        for name, value in parameters.items():
            type_ = type(value)

            edit: QtWidgets.QLineEdit = QtWidgets.QLineEdit(str(value))
            if type_ is int:
                validator: QtGui.QIntValidator = QtGui.QIntValidator()
                edit.setValidator(validator)
            elif type_ is float:
                validator: QtGui.QDoubleValidator = QtGui.QDoubleValidator()
                edit.setValidator(validator)

            form.addRow(f"{name} {type_}", edit)

            self.edits[name] = (edit, type_)

        button: QtWidgets.QPushButton = QtWidgets.QPushButton(button_text)
        button.clicked.connect(self.accept)
        form.addRow(button)

        widget: QtWidgets.QWidget = QtWidgets.QWidget()
        widget.setLayout(form)

        scroll: QtWidgets.QScrollArea = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addWidget(scroll)
        self.setLayout(vbox)

    def get_setting(self) -> dict:
        """"""
        setting: dict = {}

        for name, tp in self.edits.items():
            edit, type_ = tp
            value_text = edit.text()

            if type_ == bool:
                if value_text == "True":
                    value = True
                else:
                    value = False
            else:
                value = type_(value_text)

            setting[name] = value

        return setting


class BacktesterChart(pg.GraphicsLayoutWidget):
    """"""

    def __init__(self) -> None:
        """"""
        super().__init__(title="Backtester Chart")

        self.dates: dict = {}

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        pg.setConfigOptions(antialias=True)

        # Create plot widgets
        self.balance_plot = self.addPlot(
            title=_("账户净值"),
            axisItems={"bottom": DateAxis(self.dates, orientation="bottom")}
        )
        self.nextRow()

        self.drawdown_plot = self.addPlot(
            title=_("净值回撤"),
            axisItems={"bottom": DateAxis(self.dates, orientation="bottom")}
        )
        self.nextRow()

        self.pnl_plot = self.addPlot(
            title=_("每日盈亏"),
            axisItems={"bottom": DateAxis(self.dates, orientation="bottom")}
        )
        self.nextRow()

        self.distribution_plot = self.addPlot(title=_("盈亏分布"))

        # Add curves and bars on plot widgets
        self.balance_curve = self.balance_plot.plot(
            pen=pg.mkPen("#ffc107", width=3)
        )

        dd_color: str = "#303f9f"
        self.drawdown_curve = self.drawdown_plot.plot(
            fillLevel=-0.3, brush=dd_color, pen=dd_color
        )

        profit_color: str = 'r'
        loss_color: str = 'g'
        self.profit_pnl_bar = pg.BarGraphItem(
            x=[], height=[], width=0.3, brush=profit_color, pen=profit_color
        )
        self.loss_pnl_bar = pg.BarGraphItem(
            x=[], height=[], width=0.3, brush=loss_color, pen=loss_color
        )
        self.pnl_plot.addItem(self.profit_pnl_bar)
        self.pnl_plot.addItem(self.loss_pnl_bar)

        distribution_color: str = "#6d4c41"
        self.distribution_curve = self.distribution_plot.plot(
            fillLevel=-0.3, brush=distribution_color, pen=distribution_color
        )

    def clear_data(self) -> None:
        """"""
        self.balance_curve.setData([], [])
        self.drawdown_curve.setData([], [])
        self.profit_pnl_bar.setOpts(x=[], height=[])
        self.loss_pnl_bar.setOpts(x=[], height=[])
        self.distribution_curve.setData([], [])

    def set_data(self, df) -> None:
        """"""
        if df is None:
            return

        count: int = len(df)

        self.dates.clear()
        for n, date in enumerate(df.index):
            self.dates[n] = date

        # Set data for curve of balance and drawdown
        self.balance_curve.setData(df["balance"])
        self.drawdown_curve.setData(df["drawdown"])

        # Set data for daily pnl bar
        profit_pnl_x: list = []
        profit_pnl_height: list = []
        loss_pnl_x: list = []
        loss_pnl_height: list = []

        for count, pnl in enumerate(df["net_pnl"]):
            if pnl >= 0:
                profit_pnl_height.append(pnl)
                profit_pnl_x.append(count)
            else:
                loss_pnl_height.append(pnl)
                loss_pnl_x.append(count)

        self.profit_pnl_bar.setOpts(x=profit_pnl_x, height=profit_pnl_height)
        self.loss_pnl_bar.setOpts(x=loss_pnl_x, height=loss_pnl_height)

        # Set data for pnl distribution
        hist, x = np.histogram(df["net_pnl"], bins="doane")
        x = x[:-1]
        self.distribution_curve.setData(x, hist)


class DateAxis(pg.AxisItem):
    """Axis for showing date data"""

    def __init__(self, dates: dict, *args, **kwargs) -> None:
        """"""
        super().__init__(*args, **kwargs)
        self.dates: dict = dates

    def tickStrings(self, values, scale, spacing) -> list:
        """"""
        strings: list = []
        for v in values:
            dt = self.dates.get(v, "")
            strings.append(str(dt))
        return strings


class OptimizationSettingEditor(QtWidgets.QDialog):
    """
    For setting up parameters for optimization.
    """
    DISPLAY_NAME_MAP: dict = {
        _("总收益率"): "total_return",
        _("夏普比率"): "sharpe_ratio",
        _("EWM夏普"): "ewm_sharpe",
        _("收益回撤比"): "return_drawdown_ratio",
        _("日均盈亏"): "daily_net_pnl"
    }

    def __init__(
        self, class_name: str, parameters: dict
    ) -> None:
        """"""
        super().__init__()

        self.class_name: str = class_name
        self.parameters: dict = parameters
        self.edits: dict = {}

        self.optimization_setting: OptimizationSetting = None
        self.use_ga: bool = False

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        QLabel: QtWidgets.QLabel = QtWidgets.QLabel

        self.target_combo: QtWidgets.QComboBox = QtWidgets.QComboBox()
        self.target_combo.addItems(list(self.DISPLAY_NAME_MAP.keys()))

        self.worker_spin: QtWidgets.QSpinBox = QtWidgets.QSpinBox()
        self.worker_spin.setRange(0, 10000)
        self.worker_spin.setValue(0)
        self.worker_spin.setToolTip(_("设为0则自动根据CPU核心数启动对应数量的进程"))

        grid: QtWidgets.QGridLayout = QtWidgets.QGridLayout()
        grid.addWidget(QLabel(_("优化目标")), 0, 0)
        grid.addWidget(self.target_combo, 0, 1, 1, 3)
        grid.addWidget(QLabel(_("进程上限")), 1, 0)
        grid.addWidget(self.worker_spin, 1, 1, 1, 3)
        grid.addWidget(QLabel(_("参数")), 2, 0)
        grid.addWidget(QLabel(_("开始")), 2, 1)
        grid.addWidget(QLabel(_("步进")), 2, 2)
        grid.addWidget(QLabel(_("结束")), 2, 3)

        # Add vt_symbol and name edit if add new strategy
        self.setWindowTitle(_("优化参数配置：{}").format(self.class_name))

        validator: QtGui.QDoubleValidator = QtGui.QDoubleValidator()
        row: int = 3

        for name, value in self.parameters.items():
            type_ = type(value)
            if type_ not in [int, float]:
                continue

            start_edit: QtWidgets.QLineEdit = QtWidgets.QLineEdit(str(value))
            step_edit: QtWidgets.QLineEdit = QtWidgets.QLineEdit(str(1))
            end_edit: QtWidgets.QLineEdit = QtWidgets.QLineEdit(str(value))

            for edit in [start_edit, step_edit, end_edit]:
                edit.setValidator(validator)

            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(start_edit, row, 1)
            grid.addWidget(step_edit, row, 2)
            grid.addWidget(end_edit, row, 3)

            self.edits[name] = {
                "type": type_,
                "start": start_edit,
                "step": step_edit,
                "end": end_edit
            }

            row += 1

        parallel_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("多进程优化"))
        parallel_button.clicked.connect(self.generate_parallel_setting)
        grid.addWidget(parallel_button, row, 0, 1, 4)

        row += 1
        ga_button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("遗传算法优化"))
        ga_button.clicked.connect(self.generate_ga_setting)
        grid.addWidget(ga_button, row, 0, 1, 4)

        widget: QtWidgets.QWidget = QtWidgets.QWidget()
        widget.setLayout(grid)

        scroll: QtWidgets.QScrollArea = QtWidgets.QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(widget)

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addWidget(scroll)
        self.setLayout(vbox)

    def generate_ga_setting(self) -> None:
        """"""
        self.use_ga: bool = True
        self.generate_setting()

    def generate_parallel_setting(self) -> None:
        """"""
        self.use_ga: bool = False
        self.generate_setting()

    def generate_setting(self) -> None:
        """"""
        self.optimization_setting = OptimizationSetting()

        self.target_display: str = self.target_combo.currentText()
        target_name: str = self.DISPLAY_NAME_MAP[self.target_display]
        self.optimization_setting.set_target(target_name)

        for name, d in self.edits.items():
            type_ = d["type"]
            start_value = type_(d["start"].text())
            step_value = type_(d["step"].text())
            end_value = type_(d["end"].text())

            if start_value == end_value:
                self.optimization_setting.add_parameter(name, start_value)
            else:
                self.optimization_setting.add_parameter(
                    name,
                    start_value,
                    end_value,
                    step_value
                )

        self.accept()

    def get_setting(self) -> Tuple[OptimizationSetting, bool, int]:
        """"""
        return self.optimization_setting, self.use_ga, self.worker_spin.value()


class OptimizationResultMonitor(QtWidgets.QDialog):
    """
    For viewing optimization result.
    """

    def __init__(
        self, result_values: list, target_display: str
    ) -> None:
        """"""
        super().__init__()

        self.result_values: list = result_values
        self.target_display: str = target_display

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        self.setWindowTitle(_("参数优化结果"))
        self.resize(1100, 500)

        # Creat table to show result
        table: QtWidgets.QTableWidget = QtWidgets.QTableWidget()

        table.setColumnCount(2)
        table.setRowCount(len(self.result_values))
        table.setHorizontalHeaderLabels([_("参数"), self.target_display])
        table.setEditTriggers(table.EditTrigger.NoEditTriggers)
        table.verticalHeader().setVisible(False)

        table.horizontalHeader().setSectionResizeMode(
            0, QtWidgets.QHeaderView.ResizeMode.ResizeToContents
        )
        table.horizontalHeader().setSectionResizeMode(
            1, QtWidgets.QHeaderView.ResizeMode.Stretch
        )

        for n, tp in enumerate(self.result_values):
            setting, target_value, __ = tp
            setting_cell: QtWidgets.QTableWidgetItem = QtWidgets.QTableWidgetItem(str(setting))
            target_cell: QtWidgets.QTableWidgetItem = QtWidgets.QTableWidgetItem(f"{target_value:.2f}")

            setting_cell.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)
            target_cell.setTextAlignment(QtCore.Qt.AlignmentFlag.AlignCenter)

            table.setItem(n, 0, setting_cell)
            table.setItem(n, 1, target_cell)

        # Create layout
        button: QtWidgets.QPushButton = QtWidgets.QPushButton(_("保存"))
        button.clicked.connect(self.save_csv)

        hbox: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox.addStretch()
        hbox.addWidget(button)

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addWidget(table)
        vbox.addLayout(hbox)

        self.setLayout(vbox)

    def save_csv(self) -> None:
        """
        Save table data into a csv file
        """
        path, __ = QtWidgets.QFileDialog.getSaveFileName(
            self, _("保存数据"), "", "CSV(*.csv)")

        if not path:
            return

        with open(path, "w") as f:
            writer = csv.writer(f, lineterminator="\n")

            writer.writerow([_("参数"), self.target_display])

            for tp in self.result_values:
                setting, target_value, __ = tp
                row_data: list = [str(setting), str(target_value)]
                writer.writerow(row_data)


class BacktestingTradeMonitor(BaseMonitor):
    """
    Monitor for backtesting trade data.
    """

    headers: dict = {
        "tradeid": {"display": _("成交号 "), "cell": BaseCell, "update": False},
        "orderid": {"display": _("委托号"), "cell": BaseCell, "update": False},
        "symbol": {"display": _("代码"), "cell": BaseCell, "update": False},
        "exchange": {"display": _("交易所"), "cell": EnumCell, "update": False},
        "direction": {"display": _("方向"), "cell": DirectionCell, "update": False},
        "offset": {"display": _("开平"), "cell": EnumCell, "update": False},
        "price": {"display": _("价格"), "cell": BaseCell, "update": False},
        "volume": {"display": _("数量"), "cell": BaseCell, "update": False},
        "datetime": {"display": _("时间"), "cell": BaseCell, "update": False},
        "gateway_name": {"display": _("接口"), "cell": BaseCell, "update": False},
    }


class BacktestingOrderMonitor(BaseMonitor):
    """
    Monitor for backtesting order data.
    """

    headers: dict = {
        "orderid": {"display": _("委托号"), "cell": BaseCell, "update": False},
        "symbol": {"display": _("代码"), "cell": BaseCell, "update": False},
        "exchange": {"display": _("交易所"), "cell": EnumCell, "update": False},
        "type": {"display": _("类型"), "cell": EnumCell, "update": False},
        "direction": {"display": _("方向"), "cell": DirectionCell, "update": False},
        "offset": {"display": _("开平"), "cell": EnumCell, "update": False},
        "price": {"display": _("价格"), "cell": BaseCell, "update": False},
        "volume": {"display": _("总数量"), "cell": BaseCell, "update": False},
        "traded": {"display": _("已成交"), "cell": BaseCell, "update": False},
        "status": {"display": _("状态"), "cell": EnumCell, "update": False},
        "datetime": {"display": _("时间"), "cell": BaseCell, "update": False},
        "gateway_name": {"display": _("接口"), "cell": BaseCell, "update": False},
    }


class FloatCell(BaseCell):
    """
    Cell used for showing pnl data.
    """

    def __init__(self, content, data) -> None:
        """"""
        content: str = f"{content:.2f}"
        super().__init__(content, data)


class DailyResultMonitor(BaseMonitor):
    """
    Monitor for backtesting daily result.
    """

    headers: dict = {
        "date": {"display": _("日期"), "cell": BaseCell, "update": False},
        "trade_count": {"display": _("成交笔数"), "cell": BaseCell, "update": False},
        "start_pos": {"display": _("开盘持仓"), "cell": BaseCell, "update": False},
        "end_pos": {"display": _("收盘持仓"), "cell": BaseCell, "update": False},
        "turnover": {"display": _("成交额"), "cell": FloatCell, "update": False},
        "commission": {"display": _("手续费"), "cell": FloatCell, "update": False},
        "slippage": {"display": _("滑点"), "cell": FloatCell, "update": False},
        "trading_pnl": {"display": _("交易盈亏"), "cell": PnlCell, "update": False},
        "holding_pnl": {"display": _("持仓盈亏"), "cell": PnlCell, "update": False},
        "total_pnl": {"display": _("总盈亏"), "cell": PnlCell, "update": False},
        "net_pnl": {"display": _("净盈亏"), "cell": PnlCell, "update": False},
    }


class BacktestingResultDialog(QtWidgets.QDialog):
    """"""

    def __init__(
        self,
        main_engine: MainEngine,
        event_engine: EventEngine,
        title: str,
        table_class: QtWidgets.QTableWidget
    ) -> None:
        """"""
        super().__init__()

        self.main_engine: MainEngine = main_engine
        self.event_engine: EventEngine = event_engine
        self.title: str = title
        self.table_class: QtWidgets.QTableWidget = table_class

        self.updated: bool = False

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        self.setWindowTitle(self.title)
        self.setWindowFlags(self.windowFlags() | QtCore.Qt.WindowType.WindowMinMaxButtonsHint)
        self.resize(1400, 800)

        self.table: QtWidgets.QTableWidget = self.table_class(self.main_engine, self.event_engine)

        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addWidget(self.table)

        self.setLayout(vbox)

    def clear_data(self) -> None:
        """"""
        self.updated = False
        self.table.setRowCount(0)

    def update_data(self, data: list) -> None:
        """"""
        self.updated = True

        data.reverse()
        for obj in data:
            self.table.insert_new_row(obj)

    def is_updated(self) -> bool:
        """"""
        return self.updated

    def exec_(self):
        # 如果支持调整列宽，则自动调整
        resize_columns_func = getattr(self.table, 'resize_columns', None)
        if resize_columns_func is not None:
            resize_columns_func()
        super().exec_()


class CandleChartDialog(QtWidgets.QDialog):
    """"""

    def __init__(self) -> None:
        """"""
        super().__init__()

        self.updated: bool = False

        self.dt_ix_map: dict = {}
        self.ix_bar_map: dict = {}

        self.high_price = 0
        self.low_price = 0
        self.price_range = 0

        self.items: list = []

        self.init_ui()

    def init_ui(self) -> None:
        """"""
        self.setWindowTitle(_("回测K线图表"))
        self.resize(1400, 800)

        # Create chart widget
        self.chart: ChartWidget = ChartWidget()
        self.chart.add_plot("candle", hide_x_axis=True)
        self.chart.add_plot("volume", maximum_height=200)
        self.chart.add_item(CandleItem, "candle", "candle")
        self.chart.add_item(VolumeItem, "volume", "volume")
        self.chart.add_cursor()

        # Create help widget
        text1: str = _("红色虚线 —— 盈利交易")
        label1: QtWidgets.QLabel = QtWidgets.QLabel(text1)
        label1.setStyleSheet("color:red")

        text2: str = _("绿色虚线 —— 亏损交易")
        label2: QtWidgets.QLabel = QtWidgets.QLabel(text2)
        label2.setStyleSheet("color:#00FF00")

        text3: str = _("黄色向上箭头 —— 买入开仓 Buy")
        label3: QtWidgets.QLabel = QtWidgets.QLabel(text3)
        label3.setStyleSheet("color:yellow")

        text4: str = _("黄色向下箭头 —— 卖出平仓 Sell")
        label4: QtWidgets.QLabel = QtWidgets.QLabel(text4)
        label4.setStyleSheet("color:yellow")

        text5: str = _("紫红向下箭头 —— 卖出开仓 Short")
        label5: QtWidgets.QLabel = QtWidgets.QLabel(text5)
        label5.setStyleSheet("color:magenta")

        text6: str = _("紫红向上箭头 —— 买入平仓 Cover")
        label6: QtWidgets.QLabel = QtWidgets.QLabel(text6)
        label6.setStyleSheet("color:magenta")

        hbox1: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox1.addStretch()
        hbox1.addWidget(label1)
        hbox1.addStretch()
        hbox1.addWidget(label2)
        hbox1.addStretch()

        hbox2: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox2.addStretch()
        hbox2.addWidget(label3)
        hbox2.addStretch()
        hbox2.addWidget(label4)
        hbox2.addStretch()

        hbox3: QtWidgets.QHBoxLayout = QtWidgets.QHBoxLayout()
        hbox3.addStretch()
        hbox3.addWidget(label5)
        hbox3.addStretch()
        hbox3.addWidget(label6)
        hbox3.addStretch()

        # Set layout
        vbox: QtWidgets.QVBoxLayout = QtWidgets.QVBoxLayout()
        vbox.addWidget(self.chart)
        vbox.addLayout(hbox1)
        vbox.addLayout(hbox2)
        vbox.addLayout(hbox3)
        self.setLayout(vbox)

    def update_history(self, history: list) -> None:
        """"""
        self.updated = True
        self.chart.update_history(history)

        for ix, bar in enumerate(history):
            self.ix_bar_map[ix] = bar
            self.dt_ix_map[bar.datetime] = ix

            if not self.high_price:
                self.high_price = bar.high_price
                self.low_price = bar.low_price
            else:
                self.high_price = max(self.high_price, bar.high_price)
                self.low_price = min(self.low_price, bar.low_price)

        self.price_range = self.high_price - self.low_price

    def update_trades(self, trades: list) -> None:
        """"""
        trade_pairs: list = generate_trade_pairs(trades)

        candle_plot: pg.PlotItem = self.chart.get_plot("candle")

        scatter_data: list = []

        y_adjustment: float = self.price_range * 0.001

        for d in trade_pairs:
            open_ix = self.dt_ix_map[d["open_dt"]]
            close_ix = self.dt_ix_map[d["close_dt"]]
            open_price = d["open_price"]
            close_price = d["close_price"]

            # Trade Line
            x: list = [open_ix, close_ix]
            y: list = [open_price, close_price]

            if d["direction"] == Direction.LONG and close_price >= open_price:
                color: str = "r"
            elif d["direction"] == Direction.SHORT and close_price <= open_price:
                color: str = "r"
            else:
                color: str = "g"

            pen: QtGui.QPen = pg.mkPen(color, width=1.5, style=QtCore.Qt.PenStyle.DashLine)
            item: pg.PlotCurveItem = pg.PlotCurveItem(x, y, pen=pen)

            self.items.append(item)
            candle_plot.addItem(item)

            # Trade Scatter
            open_bar: BarData = self.ix_bar_map[open_ix]
            close_bar: BarData = self.ix_bar_map[close_ix]

            if d["direction"] == Direction.LONG:
                scatter_color: str = "yellow"
                open_symbol: str = "t1"
                close_symbol: str = "t"
                open_side: int = 1
                close_side: int = -1
                open_y: float = open_bar.low_price
                close_y: float = close_bar.high_price
            else:
                scatter_color: str = "magenta"
                open_symbol: str = "t"
                close_symbol: str = "t1"
                open_side: int = -1
                close_side: int = 1
                open_y: float = open_bar.high_price
                close_y: float = close_bar.low_price

            pen = pg.mkPen(QtGui.QColor(scatter_color))
            brush: QtGui.QBrush = pg.mkBrush(QtGui.QColor(scatter_color))
            size: int = 10

            open_scatter: dict = {
                "pos": (open_ix, open_y - open_side * y_adjustment),
                "size": size,
                "pen": pen,
                "brush": brush,
                "symbol": open_symbol
            }

            close_scatter: dict = {
                "pos": (close_ix, close_y - close_side * y_adjustment),
                "size": size,
                "pen": pen,
                "brush": brush,
                "symbol": close_symbol
            }

            scatter_data.append(open_scatter)
            scatter_data.append(close_scatter)

            # Trade text
            volume = d["volume"]
            text_color: QtGui.QColor = QtGui.QColor(scatter_color)
            open_text: pg.TextItem = pg.TextItem(f"[{volume}]", color=text_color, anchor=(0.5, 0.5))
            close_text: pg.TextItem = pg.TextItem(f"[{volume}]", color=text_color, anchor=(0.5, 0.5))

            open_text.setPos(open_ix, open_y - open_side * y_adjustment * 3)
            close_text.setPos(close_ix, close_y - close_side * y_adjustment * 3)

            self.items.append(open_text)
            self.items.append(close_text)

            candle_plot.addItem(open_text)
            candle_plot.addItem(close_text)

        trade_scatter: pg.ScatterPlotItem = pg.ScatterPlotItem(scatter_data)
        self.items.append(trade_scatter)
        candle_plot.addItem(trade_scatter)

    def clear_data(self) -> None:
        """"""
        self.updated = False

        candle_plot: pg.PlotItem = self.chart.get_plot("candle")
        for item in self.items:
            candle_plot.removeItem(item)
        self.items.clear()

        self.chart.clear_all()

        self.dt_ix_map.clear()
        self.ix_bar_map.clear()

    def is_updated(self) -> bool:
        """"""
        return self.updated


class CandleChartDialog_v2():
    """"""
    # 蜡烛图颜色

    # 交易趋势线颜色
    color_win = '#ff0000'
    color_lost = '#00ff00'
    color_buy = '#ffff00'
    color_sell = '#ffff00'
    color_short = '#ff00ff'
    color_cover = '#ff00ff'
    color_net = '#ffffff'

    def __init__(self) -> None:
        """"""
        super().__init__()
        self.updated: bool = False
        self.bars = []
        self.indicators: None|IndicatorStore = None
        self.trades = []
        self.tick_mode = False
        self._window_refs = {}

    def set_tick_mode(self, mode):
        assert mode is None or mode in TICK_BAR_MODE
        self.tick_mode = mode

    def update_history(self, history: list) -> None:
        """"""
        self.updated = True
        self.bars.extend(history)

    def update_indicators(self, indicators: None|IndicatorStore) -> None:
        """"""
        if indicators is None:
            self.indicators = None
        elif self.indicators is None:
            assert isinstance(indicators, IndicatorStore)
            self.indicators = deepcopy(indicators)
        else:
            assert self.indicators.config == indicators.config
            for name, values in self.indicators.data.items():
                self.indicators.data[name].extend(values)

    def update_trades(self, trades: list) -> None:
        """"""
        self.trades.extend(trades)

    def clear_data(self) -> None:
        """"""
        self.updated = False
        self.bars.clear()
        self.trades.clear()
        self.indicators = None

    def is_updated(self) -> bool:
        """"""
        return self.updated

    def _close_win(self, obj):
        del self._window_refs[obj.objectName()]

    def exec_(self):

        # 准备数据
        precision = 5

        # 获得K线数据
        bars = deepcopy(self.bars)

        # 清除时区
        for bar in bars:
            bar: TickData|BarData
            bar.datetime = bar.datetime.replace(tzinfo=None)

        # 获得交易对
        trades = deepcopy(self.trades)
        # 清除时区
        for trade in trades:
            trade: TradeData
            trade.datetime = trade.datetime.replace(tzinfo=None)

        trade_pairs: list = generate_trade_pairs(trades)

        # 获得指标
        indicators = self.indicators

        # ----------------------------------------------------------------------

        # 准备K线数据
        ohlcv_df = {'time': [], 'open': [], 'high': [], 'low': [], 'close': [], 'volume': [], 'open_int': []}

        if self.tick_mode is not None:
            # 如果是 tick 模式
            bar_seconds = TICK_BAR_MODE[self.tick_mode]

            last_vol = None
            tick_time = []
            tick_price = []
            tick_vol = []
            tick_open_int = []

            for bar in bars:
                assert isinstance(bar, TickData)
                if last_vol is None or last_vol > bar.volume:
                    last_vol = bar.volume
                add_vol = bar.volume - last_vol
                last_vol = bar.volume

                tick_time.append(bar.datetime)
                tick_price.append(bar.last_price)
                tick_vol.append(add_vol)
                tick_open_int.append(bar.open_interest)

            tick2bar_times, keeps, tick_bar_dict = collapse_tick_to_seccond(
                tick_time, tick_price, tick_vol, tick_open_int, bar_seconds
            )

            for nt in sorted(tick_bar_dict):
                nbar = tick_bar_dict[nt]
                ohlcv_df['time'].append(nt)
                if nbar['open'] == nbar['high'] == nbar['low'] == nbar['close'] == nbar['vol'] == nbar['open_int'] == 0.:
                    # 如果是盘前竞价时的tick，则设定为nan
                    ohlcv_df['open'].append(np.nan)
                    ohlcv_df['high'].append(np.nan)
                    ohlcv_df['low'].append(np.nan)
                    ohlcv_df['close'].append(np.nan)
                    ohlcv_df['volume'].append(np.nan)
                    ohlcv_df['open_int'].append(np.nan)
                else:
                    ohlcv_df['open'].append(nbar['open'])
                    ohlcv_df['high'].append(nbar['high'])
                    ohlcv_df['low'].append(nbar['low'])
                    ohlcv_df['close'].append(nbar['close'])
                    ohlcv_df['volume'].append(nbar['vol'])
                    ohlcv_df['open_int'].append(nbar['open_int'])

            tick2bar_times_map = dict(zip(tick_time, tick2bar_times))
            # 刷新 trade_pairs 的时间
            for pair in trade_pairs:
                pair['open_dt'] = tick2bar_times_map[pair['open_dt']]
                pair['close_dt'] = tick2bar_times_map[pair['close_dt']]

            # 刷新 ind
            if indicators is not None:
                indicators = copy(indicators)
                new_data = {}
                for ind_name, ind_data in indicators.data.items():
                    new_data[ind_name] = np.asarray(ind_data, np.object_)[keeps].tolist()
                indicators.data = new_data

        else:
            # 如果是 bar 模式
            for bar in bars:
                ohlcv_df['time'].append(bar.datetime)
                ohlcv_df['open'].append(bar.open_price)
                ohlcv_df['high'].append(bar.high_price)
                ohlcv_df['low'].append(bar.low_price)
                ohlcv_df['close'].append(bar.close_price)
                ohlcv_df['volume'].append(bar.volume)
                ohlcv_df['open_int'].append(bar.open_interest)

        ohlcv_df = DataFrame(ohlcv_df)

        # 准备结束

        # -----------------------------------------------------------------------------

        # 设定窗口，要一个非模态窗口
        widget = QtWidgets.QDialog()

        # 记录下该窗口，避免因为没有引用而被销毁
        wid = str(uuid1())
        widget.setObjectName(wid)
        self._window_refs[wid] = widget

        # 设定窗口属性
        widget.destroyed.connect(self._close_win)
        widget.setAttribute(QtCore.Qt.WidgetAttribute.WA_DeleteOnClose)     # 设定窗口关闭后就自动销毁
        widget.setWindowFlags(widget.windowFlags() | QtCore.Qt.WindowType.WindowMinMaxButtonsHint)
        widget.setWindowTitle('回测K线图表')
        layout = QVBoxLayout()
        widget.setLayout(layout)
        layout.setContentsMargins(0, 0, 0, 0)
        widget.resize(1400, 800)

        # 加入 QtChart 部件
        main_chart = QtChart(widget, inner_width=1, inner_height=1)
        layout.addWidget(main_chart.get_webview())

        # 如果存在指标，则需要多个图形，其中0号是主图
        chart_dict = {'': main_chart}
        # ----------------------------------

        if indicators is not None:
            for ind_name, ind_cfg in indicators.config.items():
                chart_name = ind_cfg.chart
                if chart_name not in chart_dict:
                    chart_dict[chart_name] = main_chart.create_subchart('bottom', 1., 0.3, sync=True)

            # 设置多个图大小
            sizes = [3] + [1] * (len(chart_dict)-1)
            add_size = sum(sizes)
            sizes = [s/add_size for s in sizes]
            for s, chart_name, chart in zip(sizes, chart_dict.keys(), chart_dict.values(), strict=True):
                # 设置图的位置和参数
                chart.resize(1., s)
                chart.legend(visible=True, text=chart_name, font_size=12, font_family='Verdana')
                chart.layout(font_size=12, font_family='Verdana')
                chart.precision(precision)
                # 设置风格
                chart.candle_style(
                    up_color='#ff3d3d00', down_color='#10cc55',
                    border_up_color='#ff3d3d', border_down_color='#10cc55',
                    wick_up_color='#ff3d3d', wick_down_color='#10cc55')

                if chart_name == '':
                    # 主图
                    chart.price_line(True, False)
                    chart.price_scale(visible=True, border_visible=False, scale_margin_top=0., scale_margin_bottom=0.1)
                    chart.volume_config(up_color='#ff3d3d', down_color='#10cc55', scale_margin_top=0.9, scale_margin_bottom=0)
                    chart.time_scale(min_bar_spacing=0., visible=True, seconds_visible=True)
                else:
                    # 非主图
                    chart.price_line(False, False)
                    chart.price_scale(visible=True, border_visible=False, scale_margin_top=0., scale_margin_bottom=0.)
                    chart.volume_config(up_color='#ff3d3d', down_color='#10cc55', scale_margin_top=0, scale_margin_bottom=0)
                    chart.time_scale(min_bar_spacing=0., visible=False, seconds_visible=False)

        # 设置主图
        code = bars[0].vt_symbol if len(bars) > 0 else ''

        main_chart.topbar.textbox('code', code)
        main_chart.topbar.textbox('label1', '红--- 盈利交易')
        main_chart.topbar.textbox('label2', '绿--- 亏损交易')
        main_chart.topbar.textbox('label3', '黄↑ 买入开仓')
        main_chart.topbar.textbox('label4', '黄↓ 卖出平仓')
        main_chart.topbar.textbox('label5', '紫↓ 卖出开仓')
        main_chart.topbar.textbox('label6', '紫↑ 买入平仓')

        main_chart.set(ohlcv_df)

        # 设置主图的买卖线
        trade_marker_list = []

        for trade_pair in trade_pairs:
            vol_str = f'[{trade_pair["volume"]}]'
            trade_pair['open_dt'] = trade_pair['open_dt'].replace(tzinfo=None)
            trade_pair['close_dt'] = trade_pair['close_dt'].replace(tzinfo=None)

            if trade_pair['direction'] == Direction.LONG:
                trade_marker_list.append({"time": trade_pair['open_dt'], "position": 'below', "shape": 'arrow_up', "color": self.color_buy, "text": vol_str})
                trade_marker_list.append({"time": trade_pair['close_dt'], "position": 'above', "shape": 'arrow_down', "color": self.color_sell, "text": vol_str})
                # main_chart.marker(trade_pair['open_dt'], 'below', 'arrow_up', self.color_buy, vol_str)
                # main_chart.marker(trade_pair['close_dt'], 'above', 'arrow_down', self.color_sell, vol_str)

                if trade_pair['close_price'] > trade_pair['open_price']:
                    line_color = self.color_win
                else:
                    line_color = self.color_lost

            elif trade_pair['direction'] == Direction.SHORT:
                trade_marker_list.append({"time": trade_pair['open_dt'], "position": 'above', "shape": 'arrow_down', "color": self.color_short, "text": vol_str})
                trade_marker_list.append({"time": trade_pair['close_dt'], "position": 'below', "shape": 'arrow_up', "color": self.color_cover, "text": vol_str})
                # main_chart.marker(trade_pair['open_dt'], 'above', 'arrow_down', self.color_short, vol_str)
                # main_chart.marker(trade_pair['close_dt'], 'below', 'arrow_up', self.color_cover, vol_str)

                if trade_pair['close_price'] < trade_pair['open_price']:
                    line_color = self.color_win
                else:
                    line_color = self.color_lost

            else:
                trade_marker_list.append({"time": trade_pair['open_dt'], "position": 'inside', "shape": 'circle', "color": self.color_net, "text": vol_str})
                trade_marker_list.append({"time": trade_pair['close_dt'], "position": 'inside', "shape": 'circle', "color": self.color_net, "text": vol_str})
                # main_chart.marker(trade_pair['open_dt'], 'inside', 'circle', self.color_net, vol_str)
                # main_chart.marker(trade_pair['close_dt'], 'inside', 'circle', self.color_net, vol_str)

                line_color = self.color_net

            main_chart.trend_line(trade_pair['open_dt'], trade_pair['open_price'],
                             trade_pair['close_dt'], trade_pair['close_price'],
                             False, line_color, 2, 'dashed')
        # 批量设定买卖标记，更快
        main_chart.marker_list(trade_marker_list)
        del trade_marker_list

        # 设置指标
        if indicators is not None:
            # 因为 mark 必须要有k线图才能显示，所以使用了mark的，都加上裸k线，没有成交量
            has_set_k = set([''])
            ohlc_df = ohlcv_df.drop(columns=['volume'])

            for ind_name, ind_cfg in indicators.config.items():
                ind_cfg: IndicatorConfig
                ind_data = indicators.data[ind_name]
                chart = chart_dict[ind_cfg.chart]
                ind_show_name = ind_cfg.display_name    # 指标显示的名称

                if ind_cfg.type == 'line':
                    df = DataFrame(ind_data, columns=[ind_show_name])
                    assert len(df[ind_show_name]) == len(ohlcv_df['time']), '错误！需要确保指标数量与时间戳数量一致'

                    df['time'] = ohlcv_df['time']

                    color = ind_cfg.color
                    thick = ind_cfg.line_thick
                    style = ind_cfg.line_style

                    line = chart.create_line(ind_show_name, color, style=style, width=thick, price_line=False, price_label=False)
                    line.set(df)
                    line.precision(precision)
                    if ind_cfg.visable:
                        line.show_data()
                    else:
                        line.hide_data()

                elif ind_cfg.type == 'mark':
                    if ind_cfg.chart not in has_set_k:
                        has_set_k.add(ind_cfg.chart)
                        chart.set(ohlc_df, keep_drawings=True)

                    marker_list = []
                    for t, m in zip(ohlcv_df['time'], ind_data, strict=True):
                        m: IndicatorMarkItem | None
                        if m is not None:
                            d = {"time": t, "position": m.position, "shape": m.shape, "color": m.color, "text": m.text}
                            marker_list.append(d)
                    chart.marker_list(marker_list)

        # lightweight-charts 的bug，如果 markers 不是按时间顺序排列，则会造成一部分markers显示出现问题
        for chart in chart_dict.values():
            # 取出 markers ，手动按时间排序，再替换回去，再更新标记
            markers = sorted(list(chart.markers.items()), key=lambda x: x[1]['time'])
            new_dict = dict(markers)
            chart.markers = new_dict
            chart._update_markers()
        # ----------------------------------------------------------------------------------

        widget.show()
        widget.activateWindow()
        # widget.exec_()

def generate_trade_pairs(trades: list) -> list:
    """"""
    long_trades: list = []
    short_trades: list = []
    trade_pairs: list = []

    for trade in trades:
        trade: TradeData = copy(trade)

        if trade.direction == Direction.LONG:
            same_direction: list = long_trades
            opposite_direction: list = short_trades
        else:
            same_direction: list = short_trades
            opposite_direction: list = long_trades

        while trade.volume and opposite_direction:
            open_trade: TradeData = opposite_direction[0]

            close_volume = min(open_trade.volume, trade.volume)
            d: dict = {
                "open_dt": open_trade.datetime,
                "open_price": open_trade.price,
                "close_dt": trade.datetime,
                "close_price": trade.price,
                "direction": open_trade.direction,
                "volume": close_volume,
            }
            trade_pairs.append(d)

            open_trade.volume -= close_volume
            if not open_trade.volume:
                opposite_direction.pop(0)

            trade.volume -= close_volume

        if trade.volume:
            same_direction.append(trade)

    return trade_pairs


def collapse_tick_to_seccond(tick_times: list[datetime], tick_price, tick_vol, tick_open_int, second_interval=1):
    '''
    把tick时间折叠到秒
    '''
    assert 60 % second_interval == 0
    assert len(tick_times) == len(tick_price) == len(tick_vol) == len(tick_open_int)

    new_times = []
    for t in tick_times:
        t: datetime
        sec_pad = second_interval - t.second % second_interval
        if sec_pad == second_interval and t.microsecond == 0:
            sec_pad = 0
        add_td = timedelta(seconds=sec_pad)

        nt = t.replace(microsecond=0) + add_td
        new_times.append(nt)

    keeps = [False] * len(new_times)
    keeps[-1] = True

    tmp_bar = {'open': None, 'high': -np.inf, 'low': np.inf, 'close': None, 'vol': 0, 'open_int': 0}

    bar_dict = {}

    for idx in range(len(new_times))[::-1]:
        if idx != len(new_times)-1 and new_times[idx] == new_times[idx+1]:
            keeps[idx] = False
            d = bar_dict[new_times[idx]]

        else:
            keeps[idx] = True
            d = bar_dict.setdefault(new_times[idx], tmp_bar.copy())

        d['open'] = tick_price[idx]
        d['high'] = max(tick_price[idx], d['high'])
        d['low'] = min(tick_price[idx], d['low'])
        if d['close'] is None:
            d['close'] = tick_price[idx]
            d['open_int'] = tick_open_int[idx]
            d['vol'] = tick_vol[idx]

    # 调整 tick_vol 到正确的 bar_vol
    sorted_times = sorted(list(bar_dict))
    for tidx, t in list(enumerate(sorted_times))[::-1]:
        if tidx == 0:
            # 第一个bar，保留原样
            continue
        cur_bar = bar_dict[t]
        before_bar = bar_dict[sorted_times[tidx-1]]
        if before_bar['vol'] < cur_bar['vol']:
            cur_bar['vol'] = cur_bar['vol'] - before_bar['vol']
        else:
            # 跨日，保留原样
            pass

    return new_times, keeps, bar_dict
