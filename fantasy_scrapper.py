import json
import re
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, Any

import requests
from bs4 import BeautifulSoup, Tag


HEADERS = {"User-Agent": "MyScraper/1.0 (+https://yourdomain.example)"}
BASE_URL = "https://www.futbolfantasy.com/jugadores/{slug}"
CACHE_DIR = Path("./scrapper")


class FantasyScraper:
    """Scraper for fantasy football player information."""
    
    def __init__(self, player_name: str):
        self.player_name = player_name
        self.cache_dir = CACHE_DIR
        self.cache_dir.mkdir(exist_ok=True)
    
    def get_player_info(self) -> Dict[str, Any]:
        """
        Get player information from cache or by scraping.
        
        Returns:
            Dictionary with player information
        """
        current_date = datetime.now().strftime("%Y%m%d")
        cache_file = self.cache_dir / f"{self.player_name}-{current_date}.json"
        
        # Clean old cache files
        self._clean_old_cache_files(current_date)
        
        # Return cached data if available
        if cache_file.exists():
            print(f"Loading data from cache: {cache_file.name}")
            return self._load_json(cache_file)
        
        # Scrape and cache new data
        print(f"No cache found. Scraping data for {self.player_name}...")
        player_data = self._scrape_player_data()
        self._save_json(cache_file, player_data)
        
        return player_data
    
    def _scrape_player_data(self) -> Dict[str, Any]:
        """Scrape player data from the website."""
        html = self._fetch_html(self.player_name)
        return self._parse_player_data(html)
    
    def _fetch_html(self, slug: str) -> str:
        """Fetch HTML content for a player."""
        url = BASE_URL.format(slug=slug)
        response = requests.get(url, headers=HEADERS, timeout=10)
        response.raise_for_status()
        return response.text
    
    def _parse_player_data(self, html: str) -> Dict[str, Any]:
        """Parse player data from HTML."""
        soup = BeautifulSoup(html, "html.parser")
        
        return {
            "jerarquia": self._extract_jerarquia(soup),
            "probabilities": self._extract_primary_probability(soup),
            "arrow_numbers": self._extract_arrow_number(soup),
            "riesgo_lesion": self._extract_rs_cuadros_phone(soup),
        }
    
    def _extract_jerarquia(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract jerarquia value from the page."""
        element = soup.select_one(".jerarquia-value")
        text = element.get_text(strip=True) if element else None

        JERARQUIA_MAP = {
            "Dios": 1,
            "Clave": 2,
            "Importante": 3,
            "Rotación": 4,
            "Revulsivo": 5,
            "Reserva": 6,
            "Descarte": 7,
        }
        mapped_value = JERARQUIA_MAP.get(text)
        return mapped_value

    def _extract_primary_probability(self, soup: BeautifulSoup) -> Optional[float]:
        """
        Extract the primary probability from prob-N classes.
        Returns the maximum probability if multiple are found.
        """
        probabilities = []
        
        for element in soup.find_all('span', class_=re.compile(r'\bprob-(\d+)')):
            text = element.get_text(strip=True)
            prob = self._parse_percentage(text)
            if prob is not None:
                probabilities.append(prob)
        
        return max(probabilities) if probabilities else None
    
    def _extract_arrow_number(self, soup: BeautifulSoup) -> Optional[int]:
        """
        Extract arrow number from arrow-N classes.
        Returns the maximum value if multiple are found.
        """
        arrow_numbers = []
        pattern = re.compile(r'arrow-(\d+)')
        
        for element in soup.find_all(class_=True):
            for class_name in element.get("class", []):
                match = pattern.match(class_name)
                if match:
                    arrow_numbers.append(int(match.group(1)))
        
        return max(arrow_numbers) if arrow_numbers else None
    
    def _extract_rs_cuadros_phone(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract rs_cuadros_phone value with multiple fallback strategies."""
        # Strategy 1: Most specific selector - risk box with mt-auto
        element = soup.select_one('.riesgo-lesion-2 .rs-cuadros-phone.mt-auto')
        if element and (text := element.get_text(strip=True)):
            return text
        
        # Strategy 2: Image alt text fallback
        img = soup.select_one('.riesgo-lesion-2 img[alt]')
        if img and img.has_attr('alt') and (alt := img['alt'].strip()):
            return alt.split()[-1]
        
        # Strategy 3: Generic mt-auto selector
        element = soup.select_one('.rs-cuadros-phone.mt-auto')
        if element and (text := element.get_text(strip=True)):
            return text
        
        # Strategy 4: First rs-cuadros-phone without <strong> tag
        for element in soup.select('.rs-cuadros-phone'):
            if not element.find('strong') and (text := element.get_text(strip=True)):
                return text
        
        # Strategy 5: Last rs-cuadros-phone element
        elements = soup.select('.rs-cuadros-phone')
        if elements:
            return elements[-1].get_text(strip=True)
        
        return None
    
    def _parse_percentage(self, text: str) -> Optional[float]:
        """Parse percentage from text and return as float (0-1)."""
        match = re.search(r'(\d+(?:\.\d+)?)\s*%', text)
        if not match:
            return None
        return float(match.group(1)) / 100.0
    
    def _clean_old_cache_files(self, current_date: str):
        """Remove cache files that don't match today's date."""
        suffix_pattern = f"-{current_date}.json"
        
        for file_path in self.cache_dir.glob("*.json"):
            if not file_path.name.endswith(suffix_pattern):
                try:
                    file_path.unlink()
                    print(f"Removed old cache file: {file_path.name}")
                except OSError as e:
                    print(f"Error removing {file_path.name}: {e}")
    
    def _load_json(self, file_path: Path) -> Dict[str, Any]:
        """Load JSON data from file."""
        with open(file_path, "r", encoding="utf-8") as f:
            return json.load(f)
    
    def _save_json(self, file_path: Path, data: Dict[str, Any]):
        """Save data as JSON to file."""
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=4, ensure_ascii=False)


def main():
    scraper = FantasyScraper("raul-asencio-1")
    player_info = scraper.get_player_info()
    print(json.dumps(player_info, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()