# Simplepush

_Integration to integrate with [Simplepush][simplepush]._

Simplepush is a lightweight app for iOS and Android.
It is used to send notifications to your phone or to everyone subscribed to a topic.

Home Assistant sends two kinds of messages:
- Tasks stay in the Simplepush app after the push is gone. They can ask for actions, text, photos and choices, and carry files and links.
- Notifications are a push with at most one input answered right from the push, and an image, audio clip or link.

Both work without any form of remote access to Home Assistant and can be end-to-end encrypted.

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

In automations, `event`, `attachments`, `action_timeout` and `actions` in the service data are gone.
Use `files`, `links`, `expires_in` and `inputs` instead (see below).

## Examples

All examples are provided in YAML.

To try them out you can create a new automation, edit the automation in YAML and copy paste the examples.
After saving the automation you can run them to try them out.

### Sending tasks

`simplepush_hacs.send_task` sends a task. `config_entry_id` picks the Simplepush entry (the action editor lists your entries).
Call it with `response_variable` and it waits for the first answer and returns it, so the automation can use the answer in its next step.
Waiting needs `expires_in`, so the wait ends when the task can no longer be answered.

Each entry also provides `notify.<name>` for Home Assistant features that take any notifier, like alerts, notify groups and blueprints. It takes the options below under `data` and returns nothing. Answers arrive as events.

| Key | Description |
| --- | --- |
| `inputs` | What the recipient answers, see [Inputs](#inputs). |
| `expires_in` | Seconds until the task expires. An expired task can no longer be answered in the app. Without it the task stays open. |
| `files` | Local file path, or a list of them, to upload and attach. Encrypted when the task is. Only files in `/config/www`, the media folders or a directory listed in [`allowlist_external_dirs`](https://www.home-assistant.io/integrations/homeassistant/#allowlist_external_dirs) are sent. |
| `links` | URL, or a list of URLs, to attach. |
| `markdown` | Show the message formatted as Markdown. The title stays plain. |
| `topic` | Topic to send to. It must be added to the Simplepush entry. Without it the task goes to your own devices. |
| `shared` | Send one task that everyone on the topic sees. The first answer settles it for all. By default everyone gets their own copy to answer. |
| `priority` | How loudly the push interrupts, 1 (minimal) to 5 (critical). Default 3. Level 5 sounds even when the phone is muted. |

The response of `simplepush_hacs.send_task`:

| Key | Description |
| --- | --- |
| `task_id` / `group_id` | The sent task. A task sent to a topic is a group with one task per recipient. |
| `status` | `completed`, or how the task ended without an answer: `expired`, `declined`, `canceled` or `deleted`. |
| `action`, `action_id` | The selected action's text and its `id`, when one was set. |
| `text` | The text answer. |
| `choice` | The chosen option. |
| `choices` | The chosen options, with `multi`. |
| `slider` | The number chosen on a slider. |
| `photo` | File path of the saved photo. |
| `photo_media_content_id` | Media source id of the saved photo, for actions that take media. |
| `voice`, `voice_media_content_id` | File path and media source id of the saved voice recording. |
| `voice_duration` | Length of the voice recording in seconds. |
| `latitude`, `longitude`, `accuracy` | The answered location, with its accuracy in meters. |
| `file`, `file_media_content_id` | File path and media source id of the saved file. |
| `completed_at` | When the answer was given. |
| `recipient`, `recipient_id` | Who answered. |

With several recipients the response holds the first answer. Every answer also fires the events described below.

### Inputs

Each entry of `inputs` has a `type`, an optional `description` shown with it, and `required` (default `true`).
The task is answered once every required input is answered. When no input is required, the first answer completes it.
Each type can be used once.

| Type | Options |
| --- | --- |
| `actions` | `actions`: the buttons. Each has an `action` (the button text), an optional `id` and an optional `style` (`primary` or `destructive`). |
| `text` | `default_value`: text the field starts with. |
| `photo` | The photo is saved to `simplepush/tasks/` in your local media folder, named by its input id. |
| `choice` | `options`: at least two. `multi`: allow choosing several. `min_selections`, `max_selections`: how many with `multi`. |
| `slider` | `min`, `max`: the scale. `step`: the steps in between, continuous without it. `unit`: a short label like `°C`. `default_value`: where the slider starts. |
| `voice` | A voice recording. It is saved to `simplepush/tasks/` in your local media folder, named by its input id. |
| `location` | The recipient's current location. |
| `file` | A file the recipient picks. It is saved to `simplepush/tasks/` in your local media folder, named by its input id. |

### Sending notifications

`simplepush_hacs.send_notification` sends a notification instead of a task.
It takes `config_entry_id`, `message`, `title`, `topic`, `shared` and `priority` like `simplepush_hacs.send_task`, and these options:

| Key | Description |
| --- | --- |
| `input` | One input answered from the push: `type: text`, `type: choice` with up to 3 `options`, or `type: actions` with up to 3 `actions` like an `actions` input. Android shows at most 3 buttons on a push. |
| `image` | URL or local file of an image shown in the push. Local files follow the same rules as `files`. |
| `audio` | URL or local file of an audio clip, instead of an image. |
| `link` | URL opened by an "Open link" button on the push, instead of an input. |
| `timeout` | Seconds to wait for the answer when called with `response_variable`. Required to wait. |

A notification does not expire. The response is the first answer with the same keys as a task's (`text`, `choice`, `action`, `action_id`, `recipient`), `notification_id` or `group_id`, and `status`: `completed`, or `pending` when nobody answered in time.
An answer after the timeout still fires `simplepush_notification_completed_event`.

```yaml
alias: Coffee in the morning
description: Ask on the lock screen whether to start the coffee machine
triggers:
  - trigger: time
    at: "06:30:00"
actions:
  - action: simplepush_hacs.send_notification
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      title: Coffee
      message: Turn on the coffee machine?
      input:
        type: actions
        actions:
          - action: Turn on
            id: coffee_on
          - action: Not now
      timeout: 900
    response_variable: answer
  - condition: template
    value_template: "{{ answer.action_id == 'coffee_on' }}"
  - action: switch.turn_on
    target:
      entity_id: switch.coffee_machine
mode: single
```

### Asking a question with actions

Sends a task with two actions (`Close` and `Leave open`) at priority 4 when the garage door has been open for 10 minutes.
The door is closed only when `Close` is selected.
`expires_in` expires the task in the app after 10 minutes, so a stale question can't be answered anymore.

```yaml
alias: Garage door left open
description: Ask whether to close the garage door
triggers:
  - trigger: state
    entity_id: cover.garage_door
    to: open
    for: "00:10:00"
actions:
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      title: Garage door
      message: The garage door has been open for 10 minutes.
      priority: 4
      expires_in: 600
      inputs:
        - type: actions
          actions:
            - action: Close
              style: primary
            - action: Leave open
    response_variable: answer
  - condition: template
    value_template: "{{ answer.action == 'Close' }}"
  - action: cover.close_cover
    target:
      entity_id: cover.garage_door
mode: single
```

### Asking for a text answer

Asks what to do when the heater has been running for an hour and passes the answer to a conversation agent.
With an LLM conversation agent the answer can be anything like "turn it off and close the blinds".
The agent can control every entity exposed to Assist, so everyone who can answer the task can control them too.
Only send such tasks to your own devices or a topic nobody else would guess.

```yaml
alias: Heater running long
description: Ask what to do with the heater and let Assist do it
triggers:
  - trigger: state
    entity_id: climate.living_room
    to: heat
    for: "01:00:00"
actions:
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      title: Heater
      message: The living room heater has been on for an hour. What should I do?
      inputs:
        - type: text
      expires_in: 1800
    response_variable: answer
  - condition: template
    value_template: "{{ answer.status == 'completed' }}"
  - action: conversation.process
    data:
      text: "{{ answer.text }}"
mode: single
```

### Asking for a photo

Asks the dog sitter for a photo of the dog every evening and forwards it to your own devices.
The saved photo is in the media folder, so it can be attached with `files` again.
`photo_media_content_id` works with actions that take media, like the attachments of `ai_task.generate_data`.

```yaml
alias: Dog photo
description: Ask the dog sitter for a photo and forward it
triggers:
  - trigger: time
    at: "19:00:00"
actions:
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      topic: dogsitter-q8f2k1
      title: Dog
      message: Please send a photo of Bello.
      inputs:
        - type: photo
      expires_in: 7200
    response_variable: answer
  - condition: template
    value_template: "{{ answer.photo is defined }}"
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      title: Bello
      message: "{{ answer.recipient }} sent a photo."
      files: "{{ answer.photo }}"
mode: single
```

### Asking to choose

Asks the family what to pick up on the way home and adds every chosen item to the shopping list.

```yaml
alias: Shopping on the way home
description: Ask what to buy and put it on the shopping list
triggers:
  - trigger: zone
    entity_id: person.alex
    zone: zone.work
    event: leave
actions:
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      topic: family-x1si3j1
      title: Shopping
      message: Alex is leaving work. What should they pick up?
      inputs:
        - type: choice
          options:
            - Milk
            - Bread
            - Eggs
            - Coffee
          multi: true
      expires_in: 1800
    response_variable: answer
  - repeat:
      for_each: "{{ answer.choices | default([]) }}"
      sequence:
        - action: todo.add_item
          target:
            entity_id: todo.shopping_list
          data:
            item: "{{ repeat.item }}"
mode: single
```

### Asking for a number

Asks for the temperature when someone comes home to a cold house and sets the thermostat to the answer.

```yaml
alias: Warm up the living room
description: Ask for the temperature and set the thermostat
triggers:
  - trigger: state
    entity_id: person.alex
    to: home
conditions:
  - condition: numeric_state
    entity_id: sensor.living_room_temperature
    below: 18
actions:
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      title: Heating
      message: It's cold in the living room. How warm should it get?
      inputs:
        - type: slider
          min: 16
          max: 24
          step: 0.5
          unit: "°C"
          default_value: 21
      expires_in: 900
    response_variable: answer
  - condition: template
    value_template: "{{ answer.slider is defined }}"
  - action: climate.set_temperature
    target:
      entity_id: climate.living_room
    data:
      temperature: "{{ answer.slider }}"
mode: single
```

### Asking for a voice message

Asks for a voice message in the afternoon and plays it on the kitchen speaker.

```yaml
alias: Message for the kids
description: Ask for a voice message and play it in the kitchen
triggers:
  - trigger: time
    at: "15:30:00"
actions:
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      topic: family-x1si3j1
      title: Message for the kids
      message: Record a message for the kids. It plays on the kitchen speaker.
      inputs:
        - type: voice
      expires_in: 3600
    response_variable: answer
  - condition: template
    value_template: "{{ answer.voice_media_content_id is defined }}"
  - action: media_player.play_media
    target:
      entity_id: media_player.kitchen
    data:
      media_content_id: "{{ answer.voice_media_content_id }}"
      media_content_type: music
mode: single
```

### Asking where someone is

Asks the dog sitter where they are during the afternoon walk and shows them on the map.
The recipient decides to answer, nothing is tracked in the background.

```yaml
alias: Where is the dog sitter
description: Ask for the dog sitter's location and put it on the map
triggers:
  - trigger: time
    at: "14:00:00"
actions:
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      topic: dogsitter-q8f2k1
      title: Walk
      message: Where are you and Bello right now?
      inputs:
        - type: location
      expires_in: 1800
    response_variable: answer
  - condition: template
    value_template: "{{ answer.latitude is defined }}"
  - action: device_tracker.see
    data:
      dev_id: dog_sitter
      gps:
        - "{{ answer.latitude }}"
        - "{{ answer.longitude }}"
      gps_accuracy: "{{ answer.accuracy | default(0) | int }}"
mode: single
```

### Asking for a file

Asks the cleaner for the invoice at the end of every month and notes where it was saved.

```yaml
alias: Cleaning invoice
description: Collect the monthly invoice as a file
triggers:
  - trigger: template
    value_template: "{{ (now() + timedelta(days=1)).day == 1 and now().hour == 18 }}"
actions:
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      topic: cleaning-7hd2m4
      title: Invoice
      message: Please send this month's invoice.
      inputs:
        - type: file
          description: The invoice as a PDF
      expires_in: 604800
    response_variable: answer
  - condition: template
    value_template: "{{ answer.file is defined }}"
  - action: logbook.log
    data:
      name: Cleaning
      message: "Invoice saved to {{ answer.file }}"
mode: single
```

### Reacting to answers with events

`simplepush_task_completed_event` is fired for every answer to a task. It carries the same keys as the `simplepush_hacs.send_task` response.
`simplepush_notification_completed_event` is fired for every answer to a notification, with the keys of the `simplepush_hacs.send_notification` response.

A `simplepush_action_triggered_event` event is fired when an action is selected, also for tasks sent with `notify`.
The event carries `action_selected`, `action_selected_at`, `task_id`, the `id` when one was set, and `recipient` when the task went to a topic.
Filter on the `id` to match the event to the task that was sent. The example below reacts to an action sent with `id: pool_pump_off`.

Events suit tasks that go to several people, where every answer counts, and answers that may take hours: a separate automation triggered by the event keeps working while nothing waits.
Home Assistant listens until the task is answered, expires or is canceled, but not across a restart.

```yaml
alias: Pool pump answers
description: Log every answer to the pool pump question
triggers:
  - trigger: event
    event_type: simplepush_action_triggered_event
    event_data:
      id: pool_pump_off
actions:
  - action: logbook.log
    data:
      name: Pool pump
      message: "{{ trigger.event.data.recipient }} wants the pump off"
mode: queued
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
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      title: Doorbell
      message: Someone is at the front door.
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
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      title: Water leak
      message: Water detected under the washing machine.
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
  - action: simplepush_hacs.send_task
    data:
      config_entry_id: 01K6ABCDEFGHJKMNPQRSTVWXYZ  # your Simplepush entry
      message: The washing machine is done.
      priority: 2
mode: single
```

### Sending end-to-end encrypted tasks

Tasks to your own devices are end-to-end encrypted with the personal password from the configuration step.
Tasks to a topic are end-to-end encrypted with the password added with the topic.
Without a password, tasks are sent unencrypted.

<!---->

[simplepush]: https://simplepu.sh
