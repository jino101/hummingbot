"""Actual controller gate bodies, isolated from compiled Hummingbot dependencies."""
import ast
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import List


class GateTests(unittest.TestCase):
    def controller(self):
        filename='controllers/generic/jino_cross_exchange_arbitrage.py'
        tree=ast.parse(Path(filename).read_text())
        tree.body=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='JinoCrossExchangeArbitrageController']
        namespace={'ArbitrageController':object,'JinoCrossExchangeArbitrageConfig':object,'List':List,'ExecutorAction':object,'Decimal':__import__('decimal').Decimal}
        exec(compile(tree,filename,'exec'),namespace)
        obj=namespace['JinoCrossExchangeArbitrageController'].__new__(namespace['JinoCrossExchangeArbitrageController'])
        obj.config=SimpleNamespace(safety_mode='live',live_readiness_max_age_seconds=120)
        obj.market_data_provider=SimpleNamespace(time=lambda:1000)
        obj.processed_data={}
        return obj

    def test_live_readiness_requires_a_recent_timestamp(self):
        controller=self.controller()
        self.assertTrue(controller._live_readiness_gate_reason())
        for stamp in (None,0,1001,879,float('nan')):
            controller.processed_data['live_readiness']={'ready':True,'checked_at':stamp}
            self.assertTrue(controller._live_readiness_gate_reason())
        controller.processed_data['live_readiness']={'ready':True,'checked_at':999}
        self.assertEqual(controller._live_readiness_gate_reason(),'')

    def test_readonly_and_failed_readiness_remain_blocked(self):
        controller=self.controller()
        controller.processed_data['live_readiness']={'ready':False,'reasons':['permission denied']}
        self.assertIn('permission denied',controller._live_readiness_gate_reason())
        controller.config.safety_mode='readonly'
        self.assertEqual(controller.determine_executor_actions(),[])
        controller.config.safety_mode='observe'
        self.assertEqual(controller.determine_executor_actions(),[])
