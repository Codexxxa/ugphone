# UgPhone Trial Auto-Buy

UgPhone Auto-Buyer is a Telegram bot designed to automate the process of purchasing TRIAL UVIP packages on UgPhone. It allows users to manage multiple UgPhone accounts, automatically check for stock/availability, and attempt to purchase the UVIP package continuously.

## Features

- **Multi-Account Support**: Manage multiple UgPhone accounts simultaneously.
- **Automated Purchasing**: Automatically attempts to purchase the Trial UVIP package every 60 seconds.
- **Real-time Status Updates**: Receive notifications on Telegram about the purchase status (success, failure, or processing).
- **Account Management**: Add, list, and remove accounts directly via Telegram commands.
- **Secure Token Handling**: Tokens are stored locally in a JSON file.

## Prerequisites

- Python 3.8 or higher
- A Telegram Bot Token (obtained from [@BotFather](https://t.me/BotFather))

## Installation

1. **Clone the repository:**
   ```bash
   git clone <repository_url>
   cd <repository_name>
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

1. Create a `.env` file in the root directory of the project.
2. Add your Telegram Bot Token to the `.env` file:
   ```env
   TELEGRAM_BOT_TOKEN=your_telegram_bot_token_here
   ```

## Usage

1. **Start the bot:**
   ```bash
   python bot.py
   ```

2. **Interact with the bot on Telegram:**

### Commands

- **/start**: detailed welcome message and command list.
- **/add**: Add a new UgPhone account. You need to provide the credentials in JSON format.
- **/list**: List all currently configured accounts.
- **/remove**: Remove an existing account.

### Adding an Account

To add an account, use the `/add` command. You will need to paste the **UGPHONE-MQTT** JSON string.

**Command Usage:**
```
/add <Paste JSON Here>
```

**JSON Format Example:**
The JSON must contain `access_token` and `login_id`.

```json
{
  "access_token": "eyJhbGciOiJIUzUxMiJ9...",
  "login_id": "123456789",
  "other_field": "..."
}
```

*Note: You can typically obtain this JSON data by inspecting the network traffic (specifically MQTT or WebSocket connection parameters) when logging into UgPhone Web.*

## Disclaimer

**IMPORTANT: READ BEFORE USE**

This software is for educational and testing purposes only. Use of this bot to automate actions on UgPhone may violate their Terms of Service.

- The developers of this bot are not responsible for any bans, account suspensions, or financial losses incurred by using this software.
- Use this tool at your own risk.
- Ensure you have a stable internet connection for the bot to function correctly.
