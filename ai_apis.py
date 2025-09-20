import json
import logging
import requests
import random
import time

# To use HuggingFace, you will need to install the library:
# pip install huggingface_hub
try:
    from huggingface_hub import InferenceClient
    from huggingface_hub.utils import HfHubHTTPError
    HUGGINGFACE_AVAILABLE = True
except ImportError:
    HUGGINGFACE_AVAILABLE = False

# --- Basic Logging Setup ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class AIManager:
    """
    Manages API interactions with various AI providers.
    This class encapsulates settings and request logic for reusability.
    """
    MAX_RETRIES = 5
    BASE_DELAY = 1

    def __init__(self, tool_name: str, api_key: str = None):
        """
        Initializes the AI Manager for a specific tool.

        Args:
            tool_name (str): The name of the AI tool to use. 
                             Must be one of the keys in _get_default_settings.
            api_key (str, optional): The API key for the service. 
                                     If not provided, it will be loaded from settings.
        """
        if tool_name not in self._get_default_settings():
            raise ValueError(f"Tool '{tool_name}' is not supported.")

        self.tool_name = tool_name
        self.settings = self._get_default_settings().get(self.tool_name, {})
        
        if api_key:
            self.settings["API_KEY"] = api_key
            
        if not self.settings.get("API_KEY") or self.settings["API_KEY"] == "putinyourkey":
             logger.warning(f"API Key for {self.tool_name} is not set. Please provide it directly or in the settings.")


    @staticmethod
    def _get_default_settings():
        """
        Contains the default configuration for all supported AI tools.
        This is the central location for all tool settings.
        """
        return {
            "Google AI": {
                "API_KEY": "putinyourkey", "MODEL": "gemini-2.5-pro", "MODELS_LIST": ["gemini-2.5-pro", "gemini-2.5-flash"],
                "system_prompt": "You are a helpful assistant.",
                "temperature": 0.7, "topK": 40, "topP": 0.95, "candidateCount": 1, "maxOutputTokens": 8192, "stopSequences": ""
            },
            "Anthropic AI": {
                "API_KEY": "putinyourkey", "MODEL": "claude-3-5-sonnet-20240620", "MODELS_LIST": ["claude-3-5-sonnet-20240620", "claude-3-opus-20240229", "claude-3-sonnet-20240229", "claude-3-haiku-20240307"],
                "system": "You are a helpful assistant.", "max_tokens": 4096, "temperature": 0.7, "top_p": 0.9, "top_k": 40, "stop_sequences": ""
            },
            "OpenAI": {
                "API_KEY": "putinyourkey", "MODEL": "gpt-4o", "MODELS_LIST": ["gpt-4o", "gpt-4-turbo", "gpt-3.5-turbo", "gpt-4o-mini"],
                "system_prompt": "You are a helpful assistant.", "temperature": 0.7, "max_tokens": 4096, "top_p": 1.0, "frequency_penalty": 0.0,
                "presence_penalty": 0.0, "seed": "", "response_format": "text", "stop": ""
            },
            "Cohere AI": {
                "API_KEY": "putinyourkey", "MODEL": "command-r-plus", "MODELS_LIST": ["command-r-plus", "command-r", "command", "command-light"],
                "preamble": "You are a helpful assistant.", "temperature": 0.7, "max_tokens": 4000, "k": 50, "p": 0.75, "frequency_penalty": 0.0,
                "presence_penalty": 0.0, "stop_sequences": "", "citation_quality": "accurate"
            },
            "HuggingFace AI": {
                "API_KEY": "putinyourkey", "MODEL": "meta-llama/Meta-Llama-3-8B-Instruct", "MODELS_LIST": ["meta-llama/Meta-Llama-3-8B-Instruct", "mistralai/Mistral-7B-Instruct-v0.2", "google/gemma-7b-it"],
                "system_prompt": "You are a helpful assistant.", "max_tokens": 4096, "temperature": 0.7, "top_p": 0.95, "stop_sequences": "", "seed": ""
            },
            "Groq AI": {
                "API_KEY": "putinyourkey", "MODEL": "llama3-70b-8192", "MODELS_LIST": ["llama3-70b-8192", "mixtral-8x7b-32768", "gemma2-9b-it"],
                "system_prompt": "You are a helpful assistant.", "temperature": 0.7, "max_tokens": 8192, "top_p": 1.0, "frequency_penalty": 0.0,
                "presence_penalty": 0.0, "stop": "", "seed": "", "response_format": "text"
            },
            "OpenRouterAI": {
                "API_KEY": "putinyourkey", "MODEL": "anthropic/claude-3.5-sonnet", "MODELS_LIST": ["anthropic/claude-3.5-sonnet", "google/gemini-flash-1.5:free", "meta-llama/llama-3-8b-instruct:free", "openai/gpt-4o-mini"],
                "system_prompt": "You are a helpful assistant.", "temperature": 0.7, "max_tokens": 4096, "top_p": 1.0, "top_k": 0, "frequency_penalty": 0.0,
                "presence_penalty": 0.0, "repetition_penalty": 1.0, "seed": "", "stop": ""
            }
        }

    def generate_response(self, prompt: str, override_settings: dict = None) -> str:
        """
        Generates a response from the selected AI provider.

        Args:
            prompt (str): The user's input prompt.
            override_settings (dict, optional): A dictionary of settings to override the defaults for this specific call.

        Returns:
            str: The AI-generated response or an error message.
        """
        current_settings = self.settings.copy()
        if override_settings:
            current_settings.update(override_settings)

        api_key = current_settings.get("API_KEY")

        if not api_key or api_key == "putinyourkey":
            return f"Error: API Key for {self.tool_name} is not set."
        if not prompt:
            return "Error: Input prompt cannot be empty."

        logger.info(f"Submitting prompt to {self.tool_name} with model {current_settings.get('MODEL')}")

        # --- HuggingFace (uses its own client) ---
        if self.tool_name == "HuggingFace AI":
            return self._handle_huggingface(prompt, current_settings, api_key)

        # --- Other Providers (REST API) ---
        return self._handle_rest_api(prompt, current_settings, api_key)

    def _handle_huggingface(self, prompt, settings, api_key):
        if not HUGGINGFACE_AVAILABLE:
            return "Error: huggingface_hub library not found. Please run 'pip install huggingface_hub'."
        try:
            client = InferenceClient(token=api_key)
            messages = []
            system_prompt = settings.get("system_prompt", "").strip()
            if system_prompt:
                messages.append({"role": "system", "content": system_prompt})
            messages.append({"role": "user", "content": prompt})

            params = {"messages": messages, "model": settings.get("MODEL")}
            
            def add_param_hf(key, p_type):
                val_str = str(settings.get(key, '')).strip()
                if val_str:
                    try:
                        converted_val = p_type(val_str)
                        if converted_val:
                            params[key] = converted_val
                    except (ValueError, TypeError):
                        logger.warning(f"Could not convert {key} value '{val_str}' to {p_type}")

            add_param_hf("max_tokens", int)
            add_param_hf("seed", int)
            add_param_hf("temperature", float)
            add_param_hf("top_p", float)
            
            stop_seq_str = str(settings.get("stop_sequences", '')).strip()
            if stop_seq_str:
                params["stop"] = [s.strip() for s in stop_seq_str.split(',')]

            logger.debug(f"HuggingFace payload: {json.dumps(params, indent=2, default=str)}")
            response_obj = client.chat_completion(**params)
            return response_obj.choices[0].message.content
        except HfHubHTTPError as e:
            error_msg = f"HuggingFace API Error: {e.response.status_code} - {e.response.reason}\n\n{e.response.text}"
            logger.error(error_msg, exc_info=True)
            return error_msg
        except Exception as e:
            logger.error(f"HuggingFace Client Error: {e}", exc_info=True)
            return f"HuggingFace Client Error: {e}"

    def _handle_rest_api(self, prompt, settings, api_key):
        url, payload, headers = "", {}, {}
        try:
            # --- Helper to safely add params ---
            def add_param(p_dict, key, p_type):
                val_str = str(settings.get(key, '')).strip()
                if val_str:
                    try:
                        converted_val = p_type(val_str)
                        if converted_val or isinstance(converted_val, (int, float)) and converted_val == 0:
                           p_dict[key] = converted_val
                    except (ValueError, TypeError):
                        logger.warning(f"Could not convert {key} value '{val_str}' to {p_type}")

            # --- Get URL and Headers ---
            url, headers = self._get_api_endpoint_and_headers(api_key)
            
            # --- Build Payload ---
            payload = self._build_payload(prompt, settings, add_param)

        except Exception as e:
            logger.error(f"Error configuring API for {self.tool_name}: {e}", exc_info=True)
            return f"Error configuring API request: {e}"

        logger.debug(f"{self.tool_name} payload: {json.dumps(payload, indent=2)}")

        for i in range(self.MAX_RETRIES):
            try:
                response = requests.post(url, json=payload, headers=headers, timeout=60)
                response.raise_for_status()
                data = response.json()
                logger.debug(f"{self.tool_name} Response: {data}")
                return self._parse_response(data)
            except requests.exceptions.HTTPError as e:
                if e.response.status_code == 429 and i < self.MAX_RETRIES - 1:
                    delay = self.BASE_DELAY * (2 ** i) + (random.uniform(0, 1))
                    logger.warning(f"Rate limit exceeded. Retrying in {delay:.2f} seconds...")
                    time.sleep(delay)
                else:
                    error_msg = f"API Request Error: {e}\nResponse: {e.response.text}"
                    logger.error(error_msg)
                    return error_msg
            except requests.exceptions.RequestException as e:
                logger.error(f"Network Error: {e}")
                return f"Network Error: {e}"
            except (KeyError, IndexError, json.JSONDecodeError) as e:
                resp_text = response.text if 'response' in locals() else 'N/A'
                logger.error(f"Error parsing AI response: {e}\nResponse:\n{resp_text}", exc_info=True)
                return f"Error parsing AI response: {e}\nResponse:\n{resp_text}"

        return "Error: Max retries exceeded. The API is still busy."

    def _get_api_endpoint_and_headers(self, api_key):
        if self.tool_name == "Google AI":
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.settings.get('MODEL')}:generateContent?key={api_key}"
            headers = {'Content-Type': 'application/json'}
        elif self.tool_name == "Anthropic AI":
            url = "https://api.anthropic.com/v1/messages"
            headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}
        elif self.tool_name == "OpenAI":
            url = "https://api.openai.com/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        elif self.tool_name == "Groq AI":
            url = "https://api.groq.com/openai/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        elif self.tool_name == "OpenRouterAI":
            url = "https://openrouter.ai/api/v1/chat/completions"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        elif self.tool_name == "Cohere AI":
            url = "https://api.cohere.com/v1/chat"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        else:
            raise ValueError(f"Unknown tool for REST API endpoint: {self.tool_name}")
        return url, headers

    def _build_payload(self, prompt, settings, add_param_func):
        payload = {}
        if self.tool_name == "Google AI":
            system_prompt = settings.get("system_prompt", "").strip()
            full_prompt = f"{system_prompt}\n\n{prompt}".strip() if system_prompt else prompt
            payload = {"contents": [{"parts": [{"text": full_prompt}], "role": "user"}]}
            gen_config = {}
            add_param_func(gen_config, 'temperature', float)
            add_param_func(gen_config, 'topP', float)
            add_param_func(gen_config, 'topK', int)
            add_param_func(gen_config, 'maxOutputTokens', int)
            add_param_func(gen_config, 'candidateCount', int)
            stop_seq_str = str(settings.get('stopSequences', '')).strip()
            if stop_seq_str: gen_config['stopSequences'] = [s.strip() for s in stop_seq_str.split(',')]
            if gen_config: payload['generationConfig'] = gen_config
        
        elif self.tool_name == "Anthropic AI":
            payload = {"model": settings.get("MODEL"), "messages": [{"role": "user", "content": prompt}]}
            if settings.get("system"): payload["system"] = settings.get("system")
            add_param_func(payload, 'max_tokens', int)
            add_param_func(payload, 'temperature', float)
            add_param_func(payload, 'top_p', float)
            add_param_func(payload, 'top_k', int)
            stop_seq_str = str(settings.get('stop_sequences', '')).strip()
            if stop_seq_str: payload['stop_sequences'] = [s.strip() for s in stop_seq_str.split(',')]

        elif self.tool_name == "Cohere AI":
            payload = {"model": settings.get("MODEL"), "message": prompt}
            if settings.get("preamble"): payload["preamble"] = settings.get("preamble")
            add_param_func(payload, 'temperature', float)
            add_param_func(payload, 'p', float)
            add_param_func(payload, 'k', int)
            add_param_func(payload, 'max_tokens', int)
            add_param_func(payload, 'frequency_penalty', float)
            add_param_func(payload, 'presence_penalty', float)
            if settings.get('citation_quality'): payload['citation_quality'] = settings['citation_quality']
            stop_seq_str = str(settings.get('stop_sequences', '')).strip()
            if stop_seq_str: payload['stop_sequences'] = [s.strip() for s in stop_seq_str.split(',')]

        elif self.tool_name in ["OpenAI", "Groq AI", "OpenRouterAI"]:
            payload = {"model": settings.get("MODEL"), "messages": []}
            system_prompt = settings.get("system_prompt", "").strip()
            if system_prompt: payload["messages"].append({"role": "system", "content": system_prompt})
            payload["messages"].append({"role": "user", "content": prompt})

            add_param_func(payload, 'temperature', float)
            add_param_func(payload, 'top_p', float)
            add_param_func(payload, 'max_tokens', int)
            add_param_func(payload, 'frequency_penalty', float)
            add_param_func(payload, 'presence_penalty', float)
            add_param_func(payload, 'seed', int)
            
            stop_str = str(settings.get('stop', '')).strip()
            if stop_str: payload['stop'] = [s.strip() for s in stop_str.split(',')]
            
            if settings.get("response_format") == "json_object": payload["response_format"] = {"type": "json_object"}
            
            if self.tool_name == "OpenRouterAI":
                add_param_func(payload, 'top_k', int)
                add_param_func(payload, 'repetition_penalty', float)
        return payload

    def _parse_response(self, data: dict) -> str:
        result_text = f"Error: Could not parse response from {self.tool_name}."
        if self.tool_name == "Google AI":
            return data.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', result_text)
        elif self.tool_name == "Anthropic AI":
            return data.get('content', [{}])[0].get('text', result_text)
        elif self.tool_name in ["OpenAI", "Groq AI", "OpenRouterAI"]:
            return data.get('choices', [{}])[0].get('message', {}).get('content', result_text)
        elif self.tool_name == "Cohere AI":
            return data.get('text', result_text)
        return result_text


if __name__ == '__main__':
    # --- DEMONSTRATION OF HOW TO USE THE AIManager ---
    
    # IMPORTANT: Replace "YOUR_API_KEY_HERE" with your actual API keys.
    # You can get them from the respective provider's website.
    
    # You only need to provide the key for the service you want to test.
    
    api_keys = {
        "Google AI": "YOUR_API_KEY_HERE",
        "Cohere AI": "YOUR_API_KEY_HERE",
        "HuggingFace AI": "YOUR_API_KEY_HERE",
        "Groq AI": "YOUR_API_KEY_HERE",
        "OpenRouterAI": "YOUR_API_KEY_HERE",
        "Anthropic AI": "YOUR_API_KEY_HERE",
        "OpenAI": "YOUR_API_KEY_HERE"
    }
    
    # --- Define the active tool and the prompt ---
    # Change this to test different providers
    ACTIVE_TOOL = "Groq AI" 
    
    # The prompt to send to the AI
    INPUT_PROMPT = "Explain the concept of quantum entanglement in simple terms."

    print(f"--- Running Test for: {ACTIVE_TOOL} ---")
    
    try:
        # 1. Initialize the manager for the active tool
        ai_manager = AIManager(tool_name=ACTIVE_TOOL, api_key=api_keys.get(ACTIVE_TOOL))
        
        # 2. (Optional) Override settings for this specific call
        # For example, to make the response more creative, you can increase the temperature.
        override_params = {
            "temperature": 0.9,
            "MODEL": "llama3-8b-8192"  # For Groq, let's use the smaller model for this test
        }
        
        # 3. Generate the response
        # The interface is simple: Input(prompt) -> Output(AI Response)
        ai_response = ai_manager.generate_response(INPUT_PROMPT, override_settings=override_params)
        
        # 4. Print the result
        print("\n--- AI Response ---")
        print(ai_response)
        print("-------------------\n")

    except ValueError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
