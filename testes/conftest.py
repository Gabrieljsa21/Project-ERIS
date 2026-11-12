"""Põe a raiz do repositório no sys.path: os testes importam o pacote `eris`
desta cópia, nunca de uma instalação editável de outra pasta."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
