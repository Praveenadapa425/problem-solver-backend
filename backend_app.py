from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import re
import json
from urllib.parse import urlparse

app = Flask(__name__)
CORS(app)

# --- HELPER ---

def extract_username(url, platform):
    parsed = urlparse(url)
    path = parsed.path.strip('/')

    if platform == 'leetcode':
        match = re.match(r"^(?:u/)?([^/]+)", path)
        if match:
            return match.group(1)
    elif platform == 'geeksforgeeks':
        match = re.search(r"(?:user/|profile/)([^/]+)", path)
        if match:
            return match.group(1)
        if path and '/' not in path:
            return path
    elif platform == 'codechef':
        match = re.match(r"users/([^/]+)", path)
        if match:
            return match.group(1)
    elif platform == 'hackerrank':
        match = re.search(r"(?:profile/)?([^/]+)", path)
        if match:
            return match.group(1)
    return None

# --- SCRAPER FUNCTIONS ---

async def fetch_leetcode_stats(url):
    username = extract_username(url, 'leetcode')
    if not username:
        return {"solved": "N/A", "url": url, "error": "Invalid LeetCode URL format."}

    graphql_api = "https://leetcode.com/graphql"
    graphql_query = {
        "query": """
        query getUserProfile($username: String!) {
          matchedUser(username: $username) {
            submitStats: submitStatsGlobal {
              acSubmissionNum { difficulty count }
            }
          }
        }""",
        "variables": {"username": username}
    }
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(graphql_api, json=graphql_query, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    return {"solved": "N/A", "url": url, "error": f"LeetCode API HTTP {resp.status} - {error_text[:100]}"}

                data = await resp.json()
                if not data.get("data") or not data["data"].get("matchedUser"):
                    return {"solved": "N/A", "url": url, "error": "LeetCode profile not found or private."}

                stats = data["data"]["matchedUser"]["submitStats"]["acSubmissionNum"]
                for stat in stats:
                    if stat["difficulty"] == "All":
                        return {"solved": stat["count"], "url": url}
                return {"solved": "N/A", "url": url, "error": "Solved count for 'All' difficulty not found."}
    except Exception as e:
        return {"solved": "N/A", "url": url, "error": f"LeetCode error: {e}"}


async def fetch_geeksforgeeks_stats(url):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={'User-Agent': 'Mozilla/5.0'}) as response:
                response.raise_for_status()
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                div = soup.find(lambda tag: tag.name == 'div' and 'Problem Solved' in tag.get_text())
                if div:
                    match = re.search(r'Problem\s*Solved\s*(\d+)', div.get_text())
                    if match:
                        return {"solved": int(match.group(1)), "url": url}

                numbers = re.findall(r'Problem\s*Solved\s*(\d+)', html)
                if numbers:
                    return {"solved": int(numbers[0]), "url": url}
        return {"solved": "N/A", "url": url, "error": "Could not parse solved count."}
    except Exception as e:
        return {"solved": "N/A", "url": url, "error": f"GFG error: {e}"}


async def fetch_codechef_stats(url):
    solved_count = "N/A"
    try:
        username = extract_username(url, 'codechef')
        if not username:
            return {"solved": "N/A", "url": url, "error": "Invalid CodeChef URL."}

        profile_url = f"https://www.codechef.com/users/{username}"
        headers = {"User-Agent": "Mozilla/5.0"}

        async with aiohttp.ClientSession() as session:
            async with session.get(profile_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                response.raise_for_status()
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")

                section = soup.find("section", class_="rating-data-section problems-solved")
                if section:
                    text = section.get_text()
                    match = re.search(r'Total\s*Problems\s*Solved:\s*(\d+)', text)
                    if match:
                        solved_count = int(match.group(1))
                    else:
                        numbers = [int(x) for x in re.findall(r'\d+', text)]
                        if numbers:
                            solved_count = max(numbers)

                if solved_count == "N/A":
                    match = re.search(r'Total\s*Problems\s*Solved:\s*(\d+)', html)
                    if match:
                        solved_count = int(match.group(1))
                    else:
                        match2 = re.search(r'Problems\s*Solved[:,]?\s*(\d+)', html)
                        if match2:
                            solved_count = int(match2.group(1))

                if solved_count != "N/A":
                    return {"solved": solved_count, "url": url}
        return {"solved": "N/A", "url": url, "error": "Solved problems not found."}
    except Exception as e:
        return {"solved": "N/A", "url": url, "error": f"CodeChef error: {e}"}


async def fetch_hackerrank_stats(url):
    username = extract_username(url, 'hackerrank')
    if not username:
        return {"solved": "N/A", "url": url, "error": "Invalid HackerRank URL."}

    headers = {'User-Agent': 'Mozilla/5.0'}
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                response.raise_for_status()
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                if soup.find('div', class_='private-profile-page-wrapper') or 'profile not found' in html.lower():
                    return {"solved": "N/A", "url": url, "error": "HackerRank profile private or not found."}

                badge_cards = soup.select('div.badge-card, div.ui-badge-card, div.hacker-badge, div.profile-badge')
                total_badges_count = len(badge_cards)

                return {"solved": total_badges_count, "url": url}
    except Exception as e:
        return {"solved": "N/A", "url": url, "error": f"HackerRank error: {e}"}


# --- ENDPOINT ---

@app.route('/api/get_stats', methods=['POST'])
async def get_stats():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data provided"}), 400

    urls = {
        'leetcode': data.get('leetcode'),
        'geeksforgeeks': data.get('geeksforgeeks'),
        'codechef': data.get('codechef'),
        'hackerrank': data.get('hackerrank')
    }
    fetchers = {
        'leetcode': fetch_leetcode_stats,
        'geeksforgeeks': fetch_geeksforgeeks_stats,
        'codechef': fetch_codechef_stats,
        'hackerrank': fetch_hackerrank_stats
    }

    tasks, platforms = [], []
    for platform, fn in fetchers.items():
        if urls[platform]:
            tasks.append(fn(urls[platform]))
            platforms.append(platform)

    results = await asyncio.gather(*tasks)

    platform_stats = {platforms[i]: results[i] for i in range(len(results))}
    for k in fetchers.keys():
        if k not in platform_stats:
            platform_stats[k] = {"solved": "N/A", "url": ""}

    total_solved = sum(
        int(data["solved"]) for k, data in platform_stats.items()
        if k != "hackerrank" and isinstance(data.get("solved"), int)
    )

    return jsonify({"platforms": platform_stats, "totalSolved": total_solved})

