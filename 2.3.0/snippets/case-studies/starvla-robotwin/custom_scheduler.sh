# Abridged architecture, not the complete 548-line launcher.
TASKS=(...50 RoboTwin task names...)
SLOT_GPUS=()
SLOT_PORTS=()
ACTIVE_PIDS=()
ACTIVE_TASKS=()
FAILED_TASKS=()

trap cleanup_active_jobs EXIT INT TERM

launch_task_in_slot() {
    start_policy_server "$gpu" "$port" &
    wait_for_server "$port"
    run_robotwin_eval "$task" "$mode" "$port"
}

while (( completed_tasks < total_tasks )); do
    for slot in "${slots[@]}"; do
        collect_finished_process "$slot"
        if slot_is_free "$slot"; then
            launch_task_in_slot "$slot" "${TASKS[$next_task]}" &
            remember_pid_task_and_logs "$slot" "$!"
        fi
    done
    sleep 5
done
