---
description: Create an API key to access Prefect Cloud from a local execution environment.
tags:
    - Prefect Cloud
    - API keys
    - configuration
search:
  boost: 2
---

# Manage Prefect Cloud API Keys <span class="badge cloud"></span>

API keys enable you to authenticate a local environment to work with Prefect Cloud.

If you run `prefect cloud login` from your CLI, you'll have the choice to authenticate through your browser or by pasting an API key.

If you choose to authenticate through your browser, you'll be directed to an authorization page.
After you grant approval to connect, you'll be redirected to the CLI and the API key will be saved to your local [Prefect profile](/guides/settings/).

If you choose to authenticate by pasting an API key, you'll need to create an API key in the Prefect Cloud UI first.

## Create an API key

To create an API key, select the account icon at the bottom-left corner of the UI.

Select **API Keys**.
The page displays a list of previously generated keys and lets you create new API keys or delete keys.

![Viewing and editing API keys in the Cloud UI.](/img/ui/cloud-api-keys.png)

Select the **+** button to create a new API key.
Provide a name for the key and an expiration date.

![Creating an API key in the Cloud UI.](/img/ui/cloud-new-api-key.png)

Note that API keys cannot be revealed again in the UI after you generate them, so copy the key to a secure location.

## Log into Prefect Cloud with an API Key

```bash
prefect cloud login -k '<my-api-key>'
```

## Service account API keys <span class="badge orgs"></span>

Service accounts are a feature of Prefect Cloud [organizations](/cloud/organizations/) that enable you to create a Prefect Cloud API key that is not associated with a user account.

Service accounts are typically used to configure API access for running workers or executing flow runs on remote infrastructure. Events and logs for flow runs in those environments are then associated with the service account rather than a user, and API access may be managed or revoked by configuring or removing the service account without disrupting user access.

See the [service accounts](../service-accounts/) documentation for more information about creating and managing service accounts in a Prefect Cloud organization.
