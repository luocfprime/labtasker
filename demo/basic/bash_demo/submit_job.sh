#!/bin/bash

# This script submits jobs with different combinations of arg1 and arg2.

# Loop through arg1 and arg2 values
for arg1 in {0..2}; do
    for arg2 in {3..5}; do
        echo "Submitting with arg1=$arg1, arg2=$arg2"
        labtasker task submit --args '{"arg1": '$arg1', "arg2": '$arg2'}'
        # Also a simpler equivalent fashion using -- as delimiter
        # labtasker task submit -- --arg1 $arg1 --arg2 $arg2
    done
done
