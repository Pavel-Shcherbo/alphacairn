"""Independent storage, transaction, disclosure and actual HTTP workbench controls."""

import copy
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from decimal import Decimal
import hashlib
import http.client
import json
import os
from pathlib import Path
import select
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from alphacairn.research_desk import ResearchDesk, examples
from alphacairn.study_evidence import verify_study_export


class ResearchDeskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.example = examples()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "research.sqlite"
        self.desk = ResearchDesk(self.path)
        self.counter = 0
        self.study = self.op("create", definition=self.example["definition"])["id"]

