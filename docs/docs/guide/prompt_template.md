# Prompt Template

This is a simple prompt to tell AI how to turn your serial task script into Labtasker submit and run script.

```markdown

    # Labtasker Task Decomposition Guide

    ## Overview
    Labtasker is a CLI tool that distributes tasks across computing resources. It uses two primary commands:
    - `labtasker task submit` - Queues task arguments for later execution
    - `labtasker loop` - Continuously fetches and executes queued tasks

    This guide will help you decompose a serial task script into Labtasker submit and run scripts.

    ## Task Decomposition Process
    For any serial task script, you need to create:
    1. A **submit script** that queues all task variations
    2. A **run script** that executes those tasks when resources are available

    ### Pattern Recognition
    - Identify loops and parameter variations in the original script
    - Move parameter generation to the submit script
    - Create a template for task execution in the run script

    ## Example 1: Simple Parameter Grid

    ### Original Script
    ```bash
    #!/bin/bash

    for arg1 in {0..2}; do
        for arg2 in {3..5}; do
            python main.py --arg1 $arg1 --arg2 $arg2
        done
    done
    ```

    ### Submit Script
    ```bash
    #!/bin/bash

    for arg1 in {0..2}; do
        for arg2 in {3..5}; do
            labtasker task submit -- --arg1 $arg1 --arg2 $arg2
        done
    done
    ```

    ### Run Script
    ```bash
    #!/bin/bash
    labtasker loop -- python main.py --arg1 '%(arg1)' --arg2 '%(arg2)'
    ```

    ## Example 2: Complex Environment and Parameters

    ### Original Script
    ```bash
    #!/bin/bash

    export CUDA_HOME=/usr/local/cuda-12.1

    BASE_LOG_DIR=/path/to/logs

    DATASETS=("imagenet" "cifar10" "mnist" "custom_dataset")
    DATASET_DESCRIPTIONS=("A person's \"image\" net" "A person's cifar 10" "A person's mnist" "A person's custom dataset")

    MODELS=("resnet50" "vit" "transformer" "alexnet")

    for idx in "${!DATASETS[@]}"; do
      for model_idx in "${!MODELS[@]}"; do

        DATASET_DESCRIPTION=${DATASET_DESCRIPTIONS[$idx]}
        DATASET=${DATASETS[$idx]}
        MODEL=${MODELS[$model_idx]}
        LOG_DIR="$BASE_LOG_DIR/$(echo "$DATASET" | tr '[:upper:]' '[:lower:]')/$MODEL"

        echo "Processing Dataset: $(echo "$DATASET" | tr '[:lower:]' '[:upper:]')"
        echo "Dataset Description: ${DATASET_DESCRIPTION}"
        echo "Model (short): ${MODEL:0:3}"
        echo "Log Directory: ${LOG_DIR}"

        # Execute training command
        python train.py --dataset "$DATASET" \
                        --dataset-description "$DATASET_DESCRIPTION" \
                        --model "$MODEL" \
                        --cuda-home "$CUDA_HOME" \
                        --log-dir "$LOG_DIR"
      done
    done

    echo "All tasks completed successfully."
    ```

    ### Submit Script
    ```bash
    #!/bin/bash

    export CUDA_HOME=/usr/local/cuda-12.1
    BASE_LOG_DIR=/path/to/logs

    DATASETS=("imagenet" "cifar10" "mnist" "custom_dataset")
    DATASET_DESCRIPTIONS=("A person's \"image\" net" "A person's cifar 10" "A person's mnist" "A person's custom dataset")
    MODELS=("resnet50" "vit" "transformer" "alexnet")

    for idx in "${!DATASETS[@]}"; do
      for model_idx in "${!MODELS[@]}"; do
        DATASET_DESCRIPTION=${DATASET_DESCRIPTIONS[$idx]}
        DATASET=${DATASETS[$idx]}
        MODEL=${MODELS[$model_idx]}
        LOG_DIR="$BASE_LOG_DIR/$(echo "$DATASET" | tr '[:upper:]' '[:lower:]')/$MODEL"

        echo "Submitting task for dataset: $DATASET, model: $MODEL"

        labtasker task submit -- \
                        --dataset "$DATASET" \
                        --dataset-description "$DATASET_DESCRIPTION" \
                        --model "$MODEL" \
                        --cuda-home "$CUDA_HOME" \
                        --log-dir "$LOG_DIR"
      done
    done

    echo "All tasks submitted successfully."
    ```

    ### Run Script
    ```bash
    #!/bin/bash
    export CUDA_HOME=/usr/local/cuda-12.1

    labtasker loop -- \
                python train.py --dataset '%(dataset)' \
                --dataset-description '%(dataset_description)' \
                --model '%(model)' \
                --cuda-home '%(cuda_home)' \
                --log-dir '%(log_dir)'
    ```

    ## Key Points to Remember

    - All variables passed to `labtasker task submit` become available as `%(variable_name)` in the run script
    - Complex values with spaces or special characters should be properly quoted
    - Environment variables and preprocessing can be included in the submit script
    - Environment variables should also be preserved in the run script in case they're needed
    - The run script acts as a template that's filled with task-specific values at runtime

    Now, I will provide an original script that needs to be decomposed for Labtasker. You need to decompose it as per the above steps.

```
