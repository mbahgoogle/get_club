import asyncio
import csv
import os
import logging
from urllib.parse import urljoin
from playwright.async_api import async_playwright, Page
from typing import List, Dict
from bs4 import BeautifulSoup
import pycountry
from tenacity import retry, stop_after_attempt, wait_fixed, retry_if_exception_type, before_sleep_log

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def get_country_code(country_name: str) -> str:
    """Convert country name to country code."""
    try:
        return pycountry.countries.lookup(country_name).alpha_2.lower()
    except LookupError:
        return "unknown"

def extract_table_data(html: str, base_url: str) -> List[Dict[str, str]]:
    """Extract player data from HTML content."""
    soup = BeautifulSoup(html, 'html.parser')
    players_list = []
    
    club_name = soup.find('h1').get_text(strip=True) if soup.find('h1') else "Unknown"
    
    table = soup.find('table', class_='items')
    if not table:
        logging.warning("Table with class 'items' not found.")
        return []
    
    tbody = table.find('tbody')
    if not tbody:
        logging.warning("No tbody found in table.")
        return []
    
    for row in tbody.find_all('tr'):
        cols = row.find_all('td')
        if len(cols) < 12:
            continue
        
        name_container = cols[1].find('table', class_='inline-table')
        if name_container:
            name_element = name_container.find('td', class_='hauptlink').find('a')
            status_element = name_container.find_all('tr')[1].find('td') if len(name_container.find_all('tr')) > 1 else None
            image_element = name_container.find('a').find('img') if name_container.find('a') else None
        else:
            name_element = None
            status_element = None
            image_element = None
        
        name = name_element.text.strip() if name_element else "Unknown"
        status = status_element.text.strip() if status_element else "Unknown"
        raw_profile_url = name_element['href'] if name_element and 'href' in name_element.attrs else ""
        profile_url = urljoin(base_url, raw_profile_url) if raw_profile_url and raw_profile_url != "#" else "Unknown"
        image_url = image_element['src'] if image_element and 'src' in image_element.attrs else "Unknown"
        
        nation_images = cols[5].find_all('img')
        nations = nation_images[0]['alt'] if nation_images and 'alt' in nation_images[0].attrs else "Unknown"
        nation_code = get_country_code(nations)
        
        player = {
            "name": name,
            "status": status,
            "profile_url": profile_url,
            "image_url": image_url,
            "nation": nations,
            "nation_code": nation_code,
            "club": club_name,
            "date_of_birth": cols[6].text.strip(),
            "appearances": cols[7].text.strip(),
            "goals": cols[8].text.strip(),
            "assists": cols[9].text.strip(),
            "own_goals": cols[10].text.strip(),
            "yellow_cards": cols[11].text.strip(),
            "second_yellow": cols[12].text.strip(),
            "red_cards": cols[13].text.strip(),
            "sub_on": cols[14].text.strip(),
            "sub_off": cols[15].text.strip(),
            "minutes_played": cols[16].text.strip(),
        }
        players_list.append(player)
    
    return players_list

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(logger, logging.INFO)
)
async def load_page(page: Page, url: str, timeout: int = 60000) -> str:
    """Load a page with retry mechanism."""
    logging.info(f"Attempting to load page: {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    html = await page.content()
    logging.info(f"Successfully loaded page: {url}")
    return html

@retry(
    stop=stop_after_attempt(3),
    wait=wait_fixed(2),
    retry=retry_if_exception_type(Exception),
    before_sleep=before_sleep_log(logger, logging.INFO)
)
async def scrape_profile_data(page: Page, profile_url: str) -> Dict[str, str]:
    """Scrape additional data from player's profile page with retry."""
    if profile_url == "Unknown":
        logging.info(f"Skipping profile scraping: Profile URL is 'Unknown'")
        return {"jersey_name": "Unknown", "full_name": "Unknown", "place_of_birth": "Unknown", "position": "Unknown", "height": "Unknown", "jersey_number": "Unknown"}
    
    logging.info(f"Starting profile scrape for URL: {profile_url}")
    html = await load_page(page, profile_url)
    soup = BeautifulSoup(html, 'html.parser')
    
    # Extract jersey name
    heading_element = soup.find('h1')
    jersey_name = heading_element.find('strong').get_text(strip=True) if heading_element and heading_element.find('strong') else "Unknown"
    logging.info(f"Extracted jersey_name: {jersey_name}")
    
    # Extract full name
    full_name_element = soup.find('span', string='Name in home country:')
    full_name = full_name_element.find_next('span', class_='info-table__content--bold').get_text(strip=True) if full_name_element else "Unknown"
    logging.info(f"Extracted full_name: {full_name}")
    
    # Extract place of birth
    place_of_birth_element = soup.find('span', string='Place of birth:')
    place_of_birth = place_of_birth_element.find_next('span', class_='info-table__content--bold').get_text(strip=True) if place_of_birth_element else "Unknown"
    logging.info(f"Extracted place_of_birth: {place_of_birth}")
    
    # Extract position
    position_element = soup.find('span', string='Position:')
    position = position_element.find_next('span', class_='info-table__content--bold').get_text(strip=True) if position_element else "Unknown"
    logging.info(f"Extracted position: {position}")
    
    # Extract height
    height_element = soup.find('span', string='Height:')
    height = height_element.find_next('span', class_='info-table__content--bold').get_text(strip=True) if height_element else "Unknown"
    logging.info(f"Extracted height: {height}")

    # Extract jersey number (dengan fallback yang lebih baik)
    jersey_element = soup.select_one('.data-header__shirt-number')
    jersey_number = jersey_element.get_text(strip=True) if jersey_element else "Unknown"
    logging.info(f"Extracted jersey_number: {jersey_number}")
    
    profile_data = {
        "jersey_name": jersey_name,
        "full_name": full_name,
        "place_of_birth": place_of_birth,
        "position": position,
        "height": height,
        "jersey_number": jersey_number
    }
    logging.info(f"Completed profile scrape for {profile_url}: {profile_data}")
    return profile_data

async def get_pagination_urls(page: Page, base_url: str) -> List[str]:
    """Collect all pagination URLs."""
    pagination_urls = [base_url]
    current_url = base_url
    
    try:
        while True:
            html = await load_page(page, current_url)
            soup = BeautifulSoup(html, 'html.parser')
            next_button = soup.find('li', class_='tm-pagination__list-item--icon-next-page')
            if next_button:
                next_link = next_button.find('a', class_='tm-pagination__link')
                if next_link and 'href' in next_link.attrs:
                    next_url = urljoin(current_url, next_link['href'])
                    if next_url not in pagination_urls:
                        pagination_urls.append(next_url)
                        current_url = next_url
                        logging.info(f"Found pagination URL: {current_url}")
                    else:
                        logging.info("Duplicate pagination URL found, stopping")
                        break
                else:
                    logging.info("No valid next URL found")
                    break
            else:
                logging.info("No more pagination pages")
                break
    except Exception as e:
        logging.error(f"Error collecting pagination URLs from {current_url}: {e}")
    
    return pagination_urls

async def scrape_page(page: Page, url: str, use_pagination: bool = True) -> List[Dict[str, str]]:
    """Scrape data from all pages with retry on page load."""
    all_data = []
    
    try:
        urls_to_scrape = [url]
        if use_pagination:
            urls_to_scrape = await get_pagination_urls(page, url)
        
        for page_url in urls_to_scrape:
            html = await load_page(page, page_url)
            logging.info(f"Scraping table data from: {page_url}")
            data = extract_table_data(html, page_url)
            all_data.extend(data)
        
        for player in all_data:
            if player["profile_url"] != "Unknown":
                profile_data = await scrape_profile_data(page, player["profile_url"])
                player.update(profile_data)
            else:
                player.update({"jersey_name": "Unknown", "full_name": "Unknown", "place_of_birth": "Unknown", "position": "Unknown", "height": "Unknown", "jersey_number": "Unknown"})
                
    except Exception as e:
        logging.error(f"Error scraping {url} after retries: {e}")
    
    return all_data

def save_to_csv(data: List[Dict[str, str]], club_name: str):
    """Save scraped data to CSV file."""
    os.makedirs("dataset", exist_ok=True)
    filename = f"{club_name.replace(' ', '_').lower()}_players_data.csv"
    filepath = os.path.join("dataset", filename)
    
    with open(filepath, mode="w", newline="", encoding="utf-8") as file:
        writer = csv.writer(file)
        writer.writerow([
            "name", "status", "profile_url", "image_url", "jersey_name", "jersey_number",
            "nation", "nation_code", "club", "place_of_birth", "full_name", "position",
            "height", "date_of_birth", "appearances", "goals", "assists", "own_goals",
            "yellow_cards", "second_yellow", "red_cards", "substituted_on", "substituted_off",
            "minutes_played"
        ])
        for player in data:
            writer.writerow([
                player["name"], player["status"], player["profile_url"], player["image_url"],
                player["jersey_name"], player["jersey_number"], player["nation"], player["nation_code"],
                player["club"], player["place_of_birth"], player["full_name"], player["position"],
                player["height"], player["date_of_birth"], player["appearances"], player["goals"],
                player["assists"], player["own_goals"], player["yellow_cards"], player["second_yellow"],
                player["red_cards"], player["sub_on"], player["sub_off"], player["minutes_played"]
            ])

        for player in data:
            writer.writerow([
                player["name"], player["status"], player["profile_url"], player["image_url"],
                player["jersey_name"], player["jersey_number"], player["nation"], player["nation_code"],
                player["
