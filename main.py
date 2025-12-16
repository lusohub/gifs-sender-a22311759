import os
import json
import requests
import redis
import random
from google.cloud import pubsub_v1

class GifSearcher:
    def __init__(self):
        # Giphy public API key (limited but free)
        self.giphy_api_key = os.environ.get('GIPHY_API_KEY', 'dc6zaTOxFJmzC')
        
    def search_gif_giphy(self, keyword):
        """Search for a random GIF using Giphy API"""
        try:
            url = "https://api.giphy.com/v1/gifs/search"
            params = {
                "api_key": self.giphy_api_key,
                "q": keyword,
                "limit": 25,
                "rating": "g",
                "lang": "en"
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('data') and len(data['data']) > 0:
                random_gif = random.choice(data['data'])
                return random_gif['images']['original']['url']
            return None
        except Exception as e:
            print(f"Error searching Giphy: {e}")
            return None
    
    def search_gif_gfycat(self, keyword):
        """Search for a random GIF using Gfycat public search"""
        try:
            # Gfycat public search endpoint
            url = f"https://api.gfycat.com/v1/gfycats/search"
            params = {
                "search_text": keyword,
                "count": 25
            }
            response = requests.get(url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('gfycats') and len(data['gfycats']) > 0:
                random_gif = random.choice(data['gfycats'])
                return random_gif.get('gifUrl') or random_gif.get('max5mbGif')
            return None
        except Exception as e:
            print(f"Error searching Gfycat: {e}")
            return None
    
    def search_gif_imgur(self, keyword):
        """Search for GIFs using Imgur public gallery"""
        try:
            # Using Imgur public gallery search
            url = "https://api.imgur.com/3/gallery/search/time/all/0"
            headers = {
                "Authorization": "Client-ID 546c25a59c58ad7"  # Public client ID
            }
            params = {
                "q": f"{keyword} gif",
                "q_type": "gif"
            }
            response = requests.get(url, headers=headers, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            if data.get('data') and len(data['data']) > 0:
                # Filter only animated GIFs
                gifs = [item for item in data['data'] if item.get('animated') or item.get('is_animated')]
                if gifs:
                    random_gif = random.choice(gifs)
                    return random_gif.get('link')
            return None
        except Exception as e:
            print(f"Error searching Imgur: {e}")
            return None
    
    def get_random_gif(self, keyword):
        """Try to get a GIF from available sources"""
        # Try all sources and collect results
        sources = [
            self.search_gif_giphy,
            self.search_gif_gfycat,
            self.search_gif_imgur
        ]
        
        # Shuffle sources for variety
        random.shuffle(sources)
        
        for source in sources:
            try:
                gif_url = source(keyword)
                if gif_url:
                    print(f"Found GIF from {source.__name__}")
                    return gif_url
            except Exception as e:
                print(f"Failed to get GIF from {source.__name__}: {e}")
                continue
        
        return None

def send_gif_to_discord(webhook_url, gif_url, keyword):
    """Send GIF to Discord webhook"""
    try:
        data = {
            "content": f"🎬 Here's a GIF for: **{keyword}**\n{gif_url}"
        }
        response = requests.post(webhook_url, json=data, timeout=10)
        response.raise_for_status()
        print(f"Sent GIF to Discord: {response.status_code}")
        return True
    except Exception as e:
        print(f"Error sending to Discord: {e}")
        return False

def callback(message):
    """Handle incoming Pub/Sub messages"""
    print(f"Received message: {message.data}")
    
    try:
        data = json.loads(message.data.decode('utf-8'))
        keyword = data.get('instruction', '').strip()
        
        if not keyword:
            print("Empty keyword received")
            message.ack()
            return
        
        print(f"Processing keyword: {keyword}")
        
        # Check cache first
        cached_gif = redis_client.get(f"gif:{keyword}")
        if cached_gif:
            gif_url = cached_gif.decode('utf-8')
            print(f"Using cached GIF: {gif_url}")
        else:
            # Search for a new GIF
            gif_url = gif_searcher.get_random_gif(keyword)
            
            if gif_url:
                # Cache the result for 30 minutes
                redis_client.setex(f"gif:{keyword}", 1800, gif_url)
                print(f"Found and cached GIF: {gif_url}")
            else:
                print(f"No GIF found for keyword: {keyword}")
                # Send a message to Discord anyway
                webhook_url = os.environ.get('DISCORD_URL')
                if webhook_url:
                    try:
                        data = {"content": f"❌ Sorry, no GIF found for: **{keyword}**"}
                        requests.post(webhook_url, json=data, timeout=10)
                    except:
                        pass
                message.ack()
                return
        
        # Send to Discord
        webhook_url = os.environ.get('DISCORD_URL')
        if webhook_url:
            success = send_gif_to_discord(webhook_url, gif_url, keyword)
            if success:
                print(f"Successfully processed keyword: {keyword}")
        else:
            print("Warning: DISCORD_URL not set")
        
        message.ack()
        
    except Exception as e:
        print(f"Error processing message: {e}")
        message.nack()

def main():
    global redis_client, gif_searcher
    
    # Initialize Redis connection
    redis_host = os.environ.get('REDIS_HOST')
    redis_port = int(os.environ.get('REDIS_PORT', 6379))
    redis_auth_string = os.environ.get('REDIS_AUTH_STRING')

    print(f"Connecting to Redis at {redis_host}:{redis_port}...")
    
    redis_client = redis.Redis(
        host=redis_host, 
        port=redis_port, 
        password=redis_auth_string, 
        decode_responses=False,
        socket_connect_timeout=5,
        socket_timeout=5,
        retry_on_timeout=True
    )
    
    try:
        redis_client.ping()
        print("Successfully connected to Redis")
    except Exception as e:
        print(f"Failed to connect to Redis: {e}")
        return
    
    # Initialize GIF searcher
    gif_searcher = GifSearcher()
    print("GIF Searcher initialized with public APIs")
    
    # Setup Pub/Sub subscriber
    project_id = os.environ.get('GCP_PROJECT_ID')
    subscription_id = os.environ.get('PUBSUB_SUBSCRIPTION_ID')
    
    if not project_id or not subscription_id:
        print("Error: GCP_PROJECT_ID and PUBSUB_SUBSCRIPTION_ID must be set")
        return
    
    subscriber = pubsub_v1.SubscriberClient()
    subscription_path = subscriber.subscription_path(project_id, subscription_id)
    
    print(f"Listening to: {subscription_path}")
    
    streaming_pull_future = subscriber.subscribe(subscription_path, callback=callback)
    
    print("Listening for messages on Pub/Sub...")
    
    try:
        streaming_pull_future.result()
    except KeyboardInterrupt:
        streaming_pull_future.cancel()
        print("Stopped listening")

if __name__ == "__main__":
    main()