# Simplepush

_Integration to integrate with [Simplepush][simplepush]._

Simplepush is a lightweight freemium app for iOS and Android.
It is used to send notifications to your phone or a group of users.

This integrations supports the following:
- Actionable notifications which work without any form of remote access to Home Assistant
- Multiple images, videos and GIFs can be attached to a single notification
- Notifications can be end-to-end encrypted

## Installation

### HACS

1. [Install HACS](https://hacs.xyz/docs/setup/download).
1. Once you have installed HACS, go to the Home Assistant web interface and click on the HACS icon in the sidebar.
1. In the HACS interface, click on the "Integrations" tab, and then click on the "Explore & Add Repositories" button.
1. Search for 'Simplepush', download the integration and restart Home Assistant

### Manual

1. Using the tool of choice open the directory (folder) for your HA configuration (where you find `configuration.yaml`).
1. If you do not have a `custom_components` directory (folder) there, you need to create it.
1. In the `custom_components` directory (folder) create a new folder called `simplepush`.
1. Download _all_ the files from the `custom_components/simplepush/` directory (folder) in this repository.
1. Place the files you downloaded in the new directory (folder) you created.
1. Restart Home Assistant
1. In the HA UI go to "Settings" -> "Integrations" click "+" and search for "Simplepush"

## Configuration

The configuration is done in the UI once you add Simplepush in the Integrations tab of the HA UI.

Just insert the Simplepush key of the device or devices you want to send notifications to.
If you want to use end-to-end encrypted notifications, add your password and salt as configured in the app.

## Examples

All examples are provided in YAML.

To try them out you can create a new automation, edit the automation in YAML and copy paste the examples.
After saving the automation you can run them to try them out.

### Sending actionable notifications

Sends an actionable notification with two actions (`yes` and `no`).
If `yes` is selected by the recipient of the actionable notification, the message `success` is written to the logbook.
If `no` is selected, nothing will happen.

In the example, the `yes` action is associated with the id '123'.
The id can then be used to filter incoming `simplepush_action_triggered_event` events.
A `simplepush_action_triggered_event` event is triggered when an action of an associated actionable notification is selected.
A timeout can be set with `action_timeout` to ignore all selected actions after the timeout.

```
alias: Actionable notification with Simplepush
description: >-
  Send an actionable notification and if triggered within 10 seconds, log success message to the
  logbook
trigger: []
condition: []
action:
  - service: notify.simplepush
    data:
      message: actionable notification
      data:
        action_timeout: 10
        actions:
          - action: "yes"
            id: 123
          - action: "no"
  - wait_for_trigger:
      - platform: event
        event_type: simplepush_action_triggered_event
        event_data:
          id: 123
  - service: logbook.log
    data:
      name: Test
      message: Success
mode: restart
```

### Sending notifications with attachments

This example automation sends a notification with two attachments to the configured Simplepush key.
The first attachment is a JPG file while the second attachment is a video with a thumbnail.

```
alias: Attachments with Simplepush
description: >-
  Send a notification with two attachments
trigger: []
condition: []
action:
  - service: notify.simplepush
    data:
      message: test
      data:
        attachments:
          - https://upload.wikimedia.org/wikipedia/commons/e/ee/Sample_abc.jpg
          - video: http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4
            thumbnail: http://commondatastorage.googleapis.com/gtv-videos-bucket/sample/images/ForBiggerEscapes.jpg
mode: restart
```

### Sending end-to-end encrypted notifications
If you defined a password and salt during the configuration step, all outgoing notifications will be end-to-end encrypted.

<!---->

[simplepush]: https://simplepush.io