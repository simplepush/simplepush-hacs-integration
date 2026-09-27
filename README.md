# Simplepush

_Integration to integrate with [Simplepush][simplepush]._

Simplepush is a lightweight app for iOS and Android.
It is used to send notifications to your phone or to everyone subscribed to a topic.

Every message from Home Assistant arrives as a task in the Simplepush app, so it stays in the app after the push is gone.

This integration supports the following:
- Actionable tasks which work without any form of remote access to Home Assistant
- Files and links attached to a task
- Tasks can be end-to-end encrypted

## Installation

### HACS (Custom Repository)

1. [Install HACS](https://hacs.xyz/docs/setup/download).
1. Once you have installed HACS, go to the Home Assistant web interface and click on the HACS icon in the sidebar.
1. Click on the 3 dots in the top right corner.
1. Select "Custom repositories".
1. Add the URL to this repository.
1. Select the "Integration" category.
1. Click the "ADD" button.
1. Click on "Simplepush HACS" in the HACS overview and download the integration.
1. Restart Home Assistant.
1. In the HA UI go to "Settings" -> "Integrations" click "+" and search for "Simplepush".
1. Select the Simplepush version without an icon.

### Manual

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
1. If you do not have a `custom_components` directory (folder) there, you need to create it.
1. In the `custom_components` directory (folder) create a new folder called `simplepush_hacs`.
1. Download _all_ the files from the `custom_components/simplepush_hacs/` directory (folder) in this repository.
1. Place the files you downloaded in the new directory (folder) you created.
1. Restart Home Assistant.
1. In the HA UI go to "Settings" -> "Integrations" click "+" and search for "Simplepush".
1. Select the Simplepush version without an icon.

## Configuration

The configuration is done in the UI once you add Simplepush in the Integrations tab of the HA UI.

| Field | Description |
| --- | --- |
| API token | Your Simplepush API token. You find it in the app under Settings. |
| Name | Name of the notify service, `notify.<name>`. |
| Password | Your personal password. It encrypts tasks to your own devices. Leave empty for unencrypted tasks. |

### Topics

To send to a topic, add it to the Simplepush entry: open the entry in Settings -> Devices & services and select "Add topic".
Enter a topic you have joined in the Simplepush app and its password, or leave the password empty for unencrypted tasks.
Home Assistant sends a test task to the topic.
To change the password later, select "Change password" on the topic.

Automations pick the topic with `topic`. A task without `topic` goes to your own devices.

### Upgrading from version 1.x

Version 1.x used a device key, password and salt. Those entries cannot be migrated.
Remove the old Simplepush entry and add it again with your API token.

In automations, `event`, `attachments` and `action_timeout` in the service data are gone.
Use `files`, `links` and `expires_in` instead (see below).

## Examples

All examples are provided in YAML.

To try them out you can create a new automation, edit the automation in YAML and copy paste the examples.
After saving the automation you can run them to try them out.

### Service data

| Key | Description |
| --- | --- |
| `actions` | List of buttons. Each entry has an `action` (the button text), an optional `id` and an optional `style` (`primary` or `destructive`). |
| `expires_in` | Seconds until the task expires. An expired task can no longer be answered in the app. Without it the task stays open. |
| `files` | Local file path, or a list of them, to upload and attach. Encrypted when the task is. Only files in `/config/www`, the media folders or a directory listed in [`allowlist_external_dirs`](https://www.home-assistant.io/integrations/homeassistant/#allowlist_external_dirs) are sent. |
| `links` | URL, or a list of URLs, to attach. |
| `topic` | Topic to send to. It must be added to the Simplepush entry. Without it the task goes to your own devices. |
| `priority` | How loudly the push interrupts, 1 (minimal) to 5 (critical). Default 3. Level 5 sounds even when the phone is muted. |

### Asking a question with actions

Sends a task with two actions (`Close` and `Leave open`) at priority 4 when the garage door has been open for 10 minutes.
Closing the door only happens when `Close` is selected.

A `simplepush_action_triggered_event` event is fired when an action is selected.
The event carries `action_selected`, `action_selected_at`, `task_id`, the `id` when one was set, and `recipient` when the task went to a topic.
Filter on the `id` to match the event to the task that was sent.

`expires_in` expires the task in the app after that many seconds, so a stale question can't be answered anymore.
Home Assistant keeps listening until the task is answered, expires or is canceled.
Set the `wait_for_trigger` timeout to the same length as `expires_in` so the automation stops waiting once the task can't be answered anymore.

```yaml
alias: Garage door left open
description: Ask whether to close the garage door
triggers:
  - trigger: state
    entity_id: cover.garage_door
    to: open
    for: "00:10:00"
actions:
  - action: notify.simplepush
    data:
      title: Garage door
      message: The garage door has been open for 10 minutes.
      data:
        priority: 4
        expires_in: 600
        actions:
          - action: Close
            id: garage_close
            style: primary
          - action: Leave open
            id: garage_leave
  - wait_for_trigger:
      - trigger: event
        event_type: simplepush_action_triggered_event
        event_data:
          id: garage_close
    timeout: "00:10:00"
    continue_on_timeout: false
  - action: cover.close_cover
    target:
      entity_id: cover.garage_door
mode: single
```

### Sending a camera snapshot

Takes a snapshot when the doorbell rings and sends it with a link to the camera dashboard.
The file is uploaded to Simplepush and end-to-end encrypted when the task is.

```yaml
alias: Doorbell snapshot
description: Send a snapshot of the front door when the doorbell rings
triggers:
  - trigger: state
    entity_id: binary_sensor.doorbell
    to: "on"
actions:
  - action: camera.snapshot
    target:
      entity_id: camera.front_door
    data:
      filename: /config/www/front-door.jpg
  - action: notify.simplepush
    data:
      title: Doorbell
      message: Someone is at the front door.
      data:
        priority: 4
        files: /config/www/front-door.jpg
        links: https://homeassistant.local:8123/dashboard-cameras
mode: single
```

### Critical alerts

Priority 5 sounds even when the phone is muted.
This example sends a leak alert to the `family-x1si3j1` topic.
Anyone who knows a topic name can subscribe to it, so pick one nobody else would guess.

```yaml
alias: Water leak
description: Wake everyone up when the washing machine leaks
triggers:
  - trigger: state
    entity_id: binary_sensor.washing_machine_leak
    to: "on"
actions:
  - action: notify.simplepush
    data:
      title: Water leak
      message: Water detected under the washing machine.
      data:
        priority: 5
        topic: family-x1si3j1
mode: single
```

### Quiet updates

Lower priorities interrupt less.
Use them for things you want to have in the app but not be bothered by.

```yaml
alias: Washing machine done
description: Note in the app that the washing machine finished
triggers:
  - trigger: state
    entity_id: sensor.washing_machine_state
    to: finished
actions:
  - action: notify.simplepush
    data:
      message: The washing machine is done.
      data:
        priority: 2
mode: single
```

### Sending end-to-end encrypted tasks

Tasks to your own devices are end-to-end encrypted with the personal password from the configuration step.
Tasks to a topic are end-to-end encrypted with the password added with the topic.
Without a password, tasks are sent unencrypted.

<!---->

[simplepush]: https://simplepu.sh
