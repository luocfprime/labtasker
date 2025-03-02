# `labtasker queue`

!!! abstract

    This page details the queue related operations.

    Queues are the basic unit of task scheduling, worker management and authentication.

## Create queue

Before submitting a task, you need to create a queue for your tasks
(this is analogous to registering an user account).

**It is recommended** to use the `create-from-config` command to create a queue
(after the config is properly setup via `labtasker config`).

```bash
labtasker queue create-from-config
```

or, you can create a queue different from the one specified in the config via `create`. See:

```bash
labtasker queue create --help
```

## Delete queue

It deletes the queue specified in the current configuration, note that with `--cascade` option,
all associated tasks and workers will be deleted.

```bash
labtasker queue delete --help
```

## Update queue

You may change the queue name, password and metadata via `update` command.

If you do not want to specify password in the command, just run

```bash
labtasker queue update
```

and an interactive prompt will be shown.

For more details, please run

```bash
labtasker queue update --help
```

## Get queue info

To get current queue info, run

```bash
labtasker queue get
```

If you are trying to use a bash script, you can use the `--quiet` option to get the queue id only.

```bash
queue_id=$(labtasker queue get --quiet)
echo $queue_id
# 30b5ef22-b45b-4f7a-ac48-d20360bbc04a
```
