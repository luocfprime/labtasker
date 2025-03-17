#!/bin/bash

for i in {1..3}
do
    for j in {1..3}
    do
        echo "Submitting with arg1=$i arg2=$j"
        labtasker task submit --max-retries 1 -- --arg1 $i --arg2 $j
    done
done
