# Duplicati Notifications

This is a simple notification service for [Duplicati](https://www.duplicati.com/).
You can setup a webhook in a backup on Duplicati to send notifications to this service, this service will then translate it to a Discord message and send it to a Discord webhook URL you provide.

[duplicati-notifications.mvl.sh](https://duplicati-notifications.mvl.sh/)

## Original project

This project is a fork of [jameslloyd/duplicati-discord-notification](https://github.com/jameslloyd/duplicati-discord-notification)

### Changes

- I've added automatic docker image builds to this repository
- I updated the Dockerfile to install pip packages with --break-system-packages
