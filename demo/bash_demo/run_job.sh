#!/bin/bash

# This script run jobs in loop by calling python job_main.py via labtasker loop
# The argument can be automatically injected into the command line via %(...) syntax
labtasker loop -c 'python demo/bash_demo/job_main.py --arg1 %(arg1) --arg2 %(arg2)'

# Also a simpler fashion:
# labtasker loop -- python demo/bash_demo/job_main.py --arg1 '%(arg1)' --arg2 '%(arg2)'
