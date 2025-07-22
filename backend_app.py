# backend_app.py
from flask import Flask, request, jsonify
from flask_cors import CORS
import asyncio
import aiohttp
from bs4 import BeautifulSoup
import re
import json # Import json for potential future JSON parsing from script tags
from urllib.parse import urlparse # Import urlparse for robust URL parsing

app = Flask(__name__)
CORS(app)

# Helper function to extract username from URLs
def extract_username(url, platform):
    """
    Extracts the username from a given profile URL based on the platform.
    """
    parsed = urlparse(url)
    path = parsed.path.strip('/')

    if platform == 'leetcode':
        # LeetCode URLs can be leetcode.com/username or leetcode.com/u/username
        match = re.match(r"^(?:u/)?([^/]+)", path)
        if match:
            return match.group(1)
    elif platform == 'geeksforgeeks':
        # GFG URLs are often like /user/username or /auth/user/profile/username
        match = re.search(r"(?:user/|profile/)([^/]+)", path)
        if match:
            return match.group(1)
        # Fallback for direct username in path if no specific path pattern
        if path and not '/' in path:
            return path
    elif platform == 'codechef':
        # CodeChef URLs are typically /users/username
        match = re.match(r"users/([^/]+)", path)
        if match:
            return match.group(1)
    elif platform == 'hackerrank':
        # HackerRank URLs can be /profile/username or just /username
        match = re.search(r"(?:profile/)?([^/]+)", path)
        if match:
            return match.group(1)
    return None


# ----- PLATFORM SCRAPER FUNCTIONS -----

async def fetch_leetcode_stats(url):
    """
    Uses LeetCode's public GraphQL endpoint for robust, real-time stats.
    """
    username = extract_username(url, 'leetcode')
    if not username:
        return {"solved": "N/A", "url": url, "error": "Invalid LeetCode URL format. Expected 'leetcode.com/username' or 'leetcode.com/u/username'."}

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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/100.0.4896.127 Safari/537.36"
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                graphql_api,
                json=graphql_query,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15) # Add a timeout
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    return {"solved": "N/A", "url": url, "error": f"LeetCode API HTTP {resp.status} - {error_text[:100]} (likely private/nonexistent/blocked)"}

                data = await resp.json()

                if not data.get("data") or not data["data"].get("matchedUser"):
                    return {"solved": "N/A", "url": url, "error": "LeetCode profile not found or is set to private."}

                stats = data["data"]["matchedUser"]["submitStats"]["acSubmissionNum"]
                for stat in stats:
                    if stat["difficulty"] == "All":
                        return {"solved": stat["count"], "url": url}
                
                return {"solved": "N/A", "url": url, "error": "LeetCode: Solved problem count for 'All' difficulty not found."}

    except aiohttp.ClientError as e:
        return {"solved": "N/A", "url": url, "error": f"LeetCode network error: {e}"}
    except asyncio.TimeoutError:
        return {"solved": "N/A", "url": url, "error": "LeetCode request timed out."}
    except json.JSONDecodeError:
        return {"solved": "N/A", "url": url, "error": "LeetCode: Invalid JSON response."}
    except Exception as e:
        return {"solved": "N/A", "url": url, "error": f"LeetCode unexpected error: {e}"}


async def fetch_geeksforgeeks_stats(url):
    """
    Scrapes GeeksforGeeks user profile for 'Problem Solved'.
    """
    print(f"Attempting to fetch GeeksforGeeks from: {url}")
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers={'User-Agent': 'Mozilla/5.0'}) as response:
                response.raise_for_status()
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                # Find "Problem Solved X" in any div
                div = soup.find(lambda tag: tag.name == 'div' and 'Problem Solved' in tag.get_text())
                if div:
                    match = re.search(r'Problem\s*Solved\s*(\d+)', div.get_text())
                    if match:
                        return {"solved": int(match.group(1)), "url": url}
                # More robust: try any "Problems" string if above fails
                numbers = re.findall(r'Problem\s*Solved\s*(\d+)', html)
                if numbers:
                    return {"solved": int(numbers[0]), "url": url}
        return {"solved": "N/A", "url": url, "error": "Could not parse solved count."}
    except aiohttp.ClientError as e:
        return {"solved": "N/A", "url": url, "error": f"GfG network error: {e}"}
    except Exception as e:
        return {"solved": "N/A", "url": url, "error": f"GfG unexpected error: {e}"}


async def fetch_codechef_stats(url):
    """
    Scrapes CodeChef for problems solved.
    """
    print(f"Attempting to fetch CodeChef from: {url}")
    solved_count = "N/A"
    try:
        # Extract username from URL
        username = extract_username(url, 'codechef')
        if not username:
            return {"solved": "N/A", "url": url, "error": "Invalid CodeChef URL format."}

        profile_url = f"https://www.codechef.com/users/{username}"
        headers = {"User-Agent": "Mozilla/5.0"}

        async with aiohttp.ClientSession() as session:
            async with session.get(profile_url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                response.raise_for_status()
                html = await response.text()
                soup = BeautifulSoup(html, "html.parser")

                # Try new UI pattern first: <section class="rating-data-section problems-solved">
                section = soup.find("section", class_="rating-data-section problems-solved")
                if section:
                    # Look for "Total Problems Solved: N"
                    text = section.get_text()
                    match = re.search(r'Total\s*Problems\s*Solved:\s*(\d+)', text)
                    if match:
                        solved_count = int(match.group(1))
                    else:
                        # Fallback: just find any number (usually the largest one) in this section
                        numbers = [int(x) for x in re.findall(r'\d+', text) if x.isdigit()]
                        if numbers:
                            solved_count = max(numbers)

                if solved_count == "N/A":
                    # Old UI fallback: check for "Problems Solved" span
                    span = soup.find(lambda tag: tag.name == 'span' and 'Problems Solved' in tag.get_text())
                    if span:
                        numbers = [int(x) for x in re.findall(r'\d+', span.get_text()) if x.isdigit()]
                        if numbers:
                            solved_count = numbers[0]

                if solved_count == "N/A":
                    # Catch-all fallback: search the entire profile page for "Total Problems Solved: N"
                    match = re.search(r'Total\s*Problems\s*Solved:\s*(\d+)', html)
                    if match:
                        solved_count = int(match.group(1))
                    else:
                        # Some high star users show it as "Problems Solved: N"
                        match2 = re.search(r'Problems\s*Solved[:,]?\s*(\d+)', html)
                        if match2:
                            solved_count = int(match2.group(1))

                if solved_count == "N/A":
                    return {"solved": "N/A", "url": url, "error": "CodeChef: Could not find solved problems count (might be private or UI changed)."}
                else:
                    return {"solved": solved_count, "url": url}

    except aiohttp.ClientError as e:
        return {"solved": "N/A", "url": url, "error": f"CodeChef network error: {e}"}
    except asyncio.TimeoutError:
        return {"solved": "N/A", "url": url, "error": "CodeChef request timed out."}
    except Exception as e:
        return {"solved": "N/A", "url": url, "error": f"CodeChef unexpected error: {e}"}


async def fetch_hackerrank_stats(url):
    """
    Attempts to scrape HackerRank profile for the count of badges.
    """
    print(f"Attempting to fetch HackerRank from: {url}")
    username = extract_username(url, 'hackerrank')
    if not username:
        return {"solved": "N/A", "url": url, "error": "Invalid HackerRank URL format."}

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as response:
                response.raise_for_status() # Raise an exception for HTTP errors (4xx or 5xx)
                html = await response.text()
                soup = BeautifulSoup(html, 'html.parser')

                # Check for private/nonexistent profile (common HackerRank pattern)
                if soup.find('div', class_='private-profile-page-wrapper') or \
                   'profile not found' in html.lower() or \
                   'page not found' in html.lower():
                    return {"solved": "N/A", "url": url, "error": "HackerRank profile private or not found."}

                # Try selecting all badge containers
                badge_cards = soup.select('div.badge-card, div.ui-badge-card, div.hacker-badge, div.profile-badge')

                if not badge_cards:
                    return {"solved": "N/A", "url": url, "error": "No badges found on HackerRank profile. (UI might have changed or no badges earned)"}

                # Count the total number of badges found
                total_badges_count = len(badge_cards)
                
                # Return the total number of badges as the 'solved' count
                return {"solved": total_badges_count, "url": url}

    except aiohttp.ClientError as e:
        return {"solved": "N/A", "url": url, "error": f"HackerRank network error: {e}"}
    except asyncio.TimeoutError:
        return {"solved": "N/A", "url": url, "error": "HackerRank request timed out."}
    except Exception as e:
        return {"solved": "N/A", "url": url, "error": f"HackerRank unexpected error: {e}"}


# ----- ENDPOINT -----

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
    tasks = []
    platform_keys_in_order = [] # To keep track of which platform corresponds to which result

    for k, fetch_fn in fetchers.items():
        if urls[k]:
            tasks.append(fetch_fn(urls[k]))
            platform_keys_in_order.append(k) # Store the platform key

    # Run all fetches asynchronously
    results = await asyncio.gather(*tasks)

    platform_stats = {}
    # Map results back to their original platforms using the order list
    for i, platform_key in enumerate(platform_keys_in_order):
        platform_stats[platform_key] = results[i]

    # Fill in N/A for platforms that were not requested
    for k in fetchers.keys():
        if k not in platform_stats:
            platform_stats[k] = {"solved": "N/A", "url": ""}


    # Calculate total, EXCLUDING HackerRank
    total_solved = 0
    for platform, data in platform_stats.items():
        if platform == 'hackerrank':
            continue # Skip HackerRank for total calculation
        
        try:
            solved_count = data.get("solved")
            if isinstance(solved_count, (int, str)) and str(solved_count).isdigit():
                total_solved += int(solved_count)
        except (ValueError, TypeError):
            pass # Ignore if conversion to int fails (e.g., "N/A")

    return jsonify({"platforms": platform_stats, "totalSolved": total_solved})


# ---------- RUN ----------
if __name__ == '__main__':
    # For true async, use: pip install hypercorn, then hypercorn backend_app:app --reload
    app.run(debug=True, port=5000)
