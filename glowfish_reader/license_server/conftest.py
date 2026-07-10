# -*- coding: utf-8 -*-
"""把 license_server/ 插入 sys.path，使测试与部署一致用扁平 import（import core/sign）。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
