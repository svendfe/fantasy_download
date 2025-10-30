Here is a comprehensive README file for your project, based on the files you provided.

-----

# La Liga Fantasy Agent 🤖

A comprehensive fantasy football tool that provides live analysis, player scouting, and intelligent transfer recommendations for your La Liga fantasy team. This agent downloads data from the official API, enriches it with external scraping, and presents all findings in an easy-to-use Streamlit dashboard.

## Features

  * **Automated Data Pipeline**: Downloads all essential data from the La Liga fantasy API, including market status, all players, and team rankings.
  * **Web Scraping Enrichment**: Scrapes `futbolfantasy.com` to gather crucial qualitative data that the API lacks, such as player hierarchy (e.g., "Clave", "Rotación"), play probability, form arrows, and injury risk.
  * **In-Depth Team Analysis**: Provides a detailed breakdown of your current team, scoring each player based on a weighted algorithm that considers form, upcoming fixtures, value for money, hierarchy, and more.
  * **Intelligent Transfer Suggestions**: Scans the market and other teams for available players, comparing them against your current squad to suggest the most valuable transfers, ranked by potential point improvement and value ratio.
  * **Fixture Difficulty Analysis**: Analyzes the upcoming fixtures for all teams in your squad to help you make informed lineup decisions.
  * **Interactive Dashboard**: A clean, multi-tab Streamlit dashboard to visualize your team analysis, upcoming fixtures, and top transfer recommendations.

## How It Works

The project is broken down into several key components:

1.  **`download_pipeline.py`**: This script connects to the La Liga fantasy API using your credentials (from `.env`) to download and save the latest game data as JSON files (e.g., market, players, teams).
2.  **`fantasy_scrapper.py`**: A web scraper that visits `futbolfantasy.com` for specific players to get qualitative metrics. It uses a local cache to avoid re-scraping data unnecessarily.
3.  **`fantasy_agent.py`**: The core logic of the application. It loads all the JSON data, enriches player objects with the scraped data, evaluates every player using a sophisticated scoring system, and finally generates a list of the best possible transfers.
4.  **`dashboard.py`**: A Streamlit application that initializes the `FantasyAgent` and presents its findings in a user-friendly web interface with multiple tabs for team analysis, fixtures, and transfers.

## Setup & Installation

1.  **Clone the Repository**

    ```bash
    git clone <your-repo-url>
    cd laliga_fantasy_agent
    ```

2.  **Set Up Environment (Conda)**
    The included `run.sh` script suggests using a Conda environment.

    ```bash
    conda create --name fantasy-agent python=3.10
    conda activate fantasy-agent
    ```

3.  **Install Dependencies**
    Install all required Python packages from `requirements.txt`.

    ```bash
    pip install -r requirements.txt
    ```

4.  **Create `.env` File**
    This project requires API credentials to fetch your league's data. Create a `.env` file in the root directory and add your credentials. The `download_pipeline.py` script requires `TOKEN_URL`, `CLIENT_ID`, and `REFRESH_TOKEN`.

    ```ini
    # .env
    TOKEN_URL="https://api.example.com/token"
    CLIENT_ID="your_client_id"
    REFRESH_TOKEN="your_refresh_token"
    ```

5.  **Create `name_mapping.json` File**
    The web scraper needs to map fantasy player nicknames (e.g., "Aarón") to their URL slugs on `futbolfantasy.com` (e.g., "aaron-escandell").
    Create an empty `name_mapping.json` file to get started. The dashboard will show an error if this file is missing.

    ```bash
    echo "{}" > name_mapping.json
    ```

    You will need to manually add mappings for players the agent fails to scrape.
    *Example:*

    ```json
    {
      "Pedri": "pedri-gonzalez",
      "Bellingham": "jude-bellingham"
    }
    ```

## Usage

You can run the agent using the provided shell script or by running the components manually.

### Option 1: Use the Run Script (Recommended)

The `run.sh` script automates the process: it activates the conda environment, runs the data pipeline, and then starts the dashboard.

Make it executable:

```bash
chmod +x run.sh
```

Then run it:

```bash
./run.sh
```

### Option 2: Manual Execution

1.  **Activate your environment:**

    ```bash
    conda activate fantasy-agent
    ```

2.  **Run the data pipeline:**
    This must be done first to get the latest data.

    ```bash
    python download_pipeline.py
    ```

3.  **Run the Streamlit Dashboard:**

    ```bash
    streamlit run dashboard.py
    ```

Open your browser to the local Streamlit URL (usually `http://localhost:8501`) to view the agent's analysis.

## Project Structure

```
.
├── dashboard.py           # Streamlit web interface
├── fantasy_agent.py       # Core logic for player evaluation and transfer analysis
├── fantasy_scrapper.py    # Scrapes futbolfantasy.com for qualitative data
├── download_pipeline.py   # Fetches and saves all data from the La Liga API
├── run.sh                 # Main execution script
├── requirements.txt       # Python dependencies
├── name_mapping.json      # (User-created) Maps player names to scraper slugs
├── .env                   # (User-created) API credentials
├── .gitignore             # Ignores downloaded data, logs, and .env
├── scrapper/              # (Auto-generated) Cache for web scraper
├── market/                # (Auto-generated) Downloaded market data
├── players/               # (Auto-generated) Downloaded player data
├── equipos/               # (Auto-generated) Downloaded team data
└── ...                    # Other generated data directories
```