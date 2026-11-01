"""Eastern Bank householding POC engine.

Import order note: every module here is pure pandas. There is no Spark import
at module level anywhere, which is what lets the same package run on a laptop
and inside a Databricks notebook.
"""

__version__ = "0.1.0"
