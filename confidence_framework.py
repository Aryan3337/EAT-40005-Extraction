"""
confidence_framework.py
=========================================
P85 – Mandi Climate Knowledge Graph Project  |  EAT40005 
 
Confidence Framework for Research Paper Validation.
 
Exit codes (mirrors script.py's sys.exit pattern):
    0 = APPROVED     → safe to pass to run_kg_extraction()
    2 = MANUAL REVIEW → hold; check review_queue.csv
    1 = REJECTED     → skip; check rejection_logs/
"""
import sys
import csv
import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import List, Dict, Tuple, Any, Optional
import pdfplumber
