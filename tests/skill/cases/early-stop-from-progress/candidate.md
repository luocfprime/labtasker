Apply our early-stop rule to the `orchid-tuning` batch: cancel a running trial
only when its latest progress has reached at least 1,000 steps and its
`best_val_loss` is above 0.90. Tell me which trial you stopped and the latest
progress that justified it. Leave trials without enough evidence, completed
work, and other batches untouched; do not requeue or start anything.
