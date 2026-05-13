from flask import Flask, request, jsonify
from flask_cors import CORS
import json
import time
import os
from Utilities.until import load_accounts
from Api.Account import get_garena_token, get_major_login
from Api.InGame import get_player_personal_show, get_player_stats, search_account_by_keyword


accounts = load_accounts()

app = Flask(__name__)
CORS(app)

# Token cache: { region: { 'token': str, 'serverUrl': str, 'expires_at': float } }
_token_cache = {}
# Refresh token 10 minutes before it actually expires
_TOKEN_REFRESH_MARGIN = 600


def get_login(region):
    """
    Return a cached (token, serverUrl) for the given region.
    Re-authenticates only when the token is expired or about to expire.
    """
    now = time.time()
    cached = _token_cache.get(region)

    if cached and cached['expires_at'] - now > _TOKEN_REFRESH_MARGIN:
        return cached['token'], cached['serverUrl']

    # Garena auth
    auth = get_garena_token(accounts[region]['uid'], accounts[region]['password'])
    if not auth or 'access_token' not in auth:
        return None, None

    # Major login
    login = get_major_login(auth['access_token'], auth['open_id'])
    if not login or 'token' not in login:
        return None, None

    ttl = login.get('ttl', 28800)
    _token_cache[region] = {
        'token': login['token'],
        'serverUrl': login['serverUrl'],
        'expires_at': now + ttl,
    }

    return login['token'], login['serverUrl']


@app.route('/info', methods=['GET'])
def get_info():
    try:
        uid = request.args.get('uid') or request.args.get('info')
        region = (request.args.get('region') or request.args.get('server', 'IND')).upper()

        if not uid:
            return json.dumps({"error": "uid parameter is required. Usage: /info?uid=<UID>&region=<REGION>"}, indent=2), 400, {'Content-Type': 'application/json; charset=utf-8'}

        try:
            uid_int = int(uid)
            if uid_int <= 0:
                return json.dumps({"error": "uid must be a positive integer"}, indent=2), 400, {'Content-Type': 'application/json; charset=utf-8'}
        except (ValueError, TypeError):
            return json.dumps({"error": "uid must be a valid integer"}, indent=2), 400, {'Content-Type': 'application/json; charset=utf-8'}

        if region not in accounts:
            return json.dumps({"error": f"Invalid region '{region}'. Available: {list(accounts.keys())}"}, indent=2), 400, {'Content-Type': 'application/json; charset=utf-8'}

        token, server_url = get_login(region)
        if not token:
            return json.dumps({"error": "Authentication failed"}, indent=2), 401, {'Content-Type': 'application/json; charset=utf-8'}

        data = get_player_personal_show(server_url, token, uid_int)
        if not data:
            return json.dumps({"error": f"No player found for uid {uid} in region {region}"}, indent=2), 404, {'Content-Type': 'application/json; charset=utf-8'}

        return json.dumps(data, indent=2, ensure_ascii=False), 200, {'Content-Type': 'application/json; charset=utf-8'}

    except Exception as e:
        return json.dumps({"error": f"Internal server error: {str(e)}"}, indent=2), 500, {'Content-Type': 'application/json; charset=utf-8'}


@app.route('/get_search_account_by_keyword', methods=['GET'])
def get_search_account_by_keyword():
    try:
        region = request.args.get('server', 'IND').upper()
        search_term = request.args.get('keyword')

        if not search_term:
            return json.dumps({"error": "Keyword parameter is required"}, indent=2), 400, {'Content-Type': 'application/json; charset=utf-8'}

        if len(search_term.strip()) < 3:
            return json.dumps({"error": "Keyword must be at least 3 characters long"}, indent=2), 400, {'Content-Type': 'application/json; charset=utf-8'}

        if region not in accounts:
            return json.dumps({"error": f"Invalid server: {region}"}, indent=2), 400, {'Content-Type': 'application/json; charset=utf-8'}

        token, server_url = get_login(region)
        if not token:
            return json.dumps({"error": "Authentication failed"}, indent=2), 401, {'Content-Type': 'application/json; charset=utf-8'}

        search_results = search_account_by_keyword(server_url, token, search_term)
        return json.dumps(search_results, indent=2, ensure_ascii=False), 200, {'Content-Type': 'application/json; charset=utf-8'}

    except KeyError as e:
        return json.dumps({"error": f"Missing configuration: {str(e)}"}, indent=2), 500, {'Content-Type': 'application/json; charset=utf-8'}
    except Exception as e:
        return json.dumps({"error": f"Internal server error: {str(e)}"}, indent=2), 500, {'Content-Type': 'application/json; charset=utf-8'}


@app.route('/get_player_stats', methods=['GET'])
def get_player_stat():
    try:
        server = request.args.get('server', 'IND').upper()
        uid = request.args.get('uid')
        gamemode = request.args.get('gamemode', 'br').lower()
        matchmode = request.args.get('matchmode', 'CAREER').upper()

        if not uid:
            return jsonify({"success": False, "error": "Missing required parameter", "message": "UID parameter is required"}), 400

        if not uid.isdigit():
            return jsonify({"success": False, "error": "Invalid UID", "message": "UID must be a numeric value"}), 400

        if server not in accounts:
            return jsonify({"success": False, "error": "Invalid server", "message": f"Server '{server}' not found. Available servers: {list(accounts.keys())}"}), 400

        if gamemode not in ['br', 'cs']:
            return jsonify({"success": False, "error": "Invalid gamemode", "message": "Gamemode must be 'br' or 'cs'"}), 400

        if matchmode not in ['CAREER', 'NORMAL', 'RANKED']:
            return jsonify({"success": False, "error": "Invalid matchmode", "message": "Matchmode must be 'CAREER', 'NORMAL', or 'RANKED'"}), 400

        token, server_url = get_login(server)
        if not token:
            return jsonify({"success": False, "error": "Authentication failed", "message": "Could not obtain auth token"}), 401

        try:
            player_stats = get_player_stats(token, server_url, gamemode, uid, matchmode)

            if not player_stats:
                return jsonify({"success": False, "error": "No stats data", "message": "No player statistics found for the given parameters"}), 404

            return jsonify({"success": True, "data": player_stats, "metadata": {"server": server, "uid": uid, "gamemode": gamemode, "matchmode": matchmode}}), 200

        except ValueError as e:
            return jsonify({"success": False, "error": "Invalid request parameters", "message": str(e)}), 400
        except ConnectionError as e:
            return jsonify({"success": False, "error": "Connection error", "message": str(e)}), 503
        except Exception as e:
            return jsonify({"success": False, "error": "Stats retrieval error", "message": str(e)}), 500

    except Exception as e:
        return jsonify({"success": False, "error": "Internal server error", "message": "An unexpected error occurred"}), 500


@app.route('/get_player_personal_show', methods=['GET'])
def get_account_info():
    try:
        server = request.args.get('server', 'IND').upper()
        uid = request.args.get('uid')
        need_gallery_info = request.args.get('need_gallery_info', False)
        call_sign_src = request.args.get('call_sign_src', 7)

        if not uid:
            return jsonify({"status": "error", "error": "Missing UID", "message": "Empty 'uid' parameter.", "code": "MISSING_UID"}), 400

        try:
            uid_int = int(uid)
            if uid_int <= 0:
                return jsonify({"status": "error", "error": "Invalid UID", "message": "UID must be a positive integer.", "code": "INVALID_UID_RANGE"}), 400
        except (ValueError, TypeError):
            return jsonify({"status": "error", "error": "Invalid UID", "message": "UID must be a valid integer.", "code": "INVALID_UID_FORMAT"}), 400

        if server not in accounts:
            return jsonify({"status": "error", "error": "Invalid Server", "message": f"Server '{server}' not found. Available: {list(accounts.keys())}", "code": "SERVER_NOT_FOUND"}), 400

        try:
            if isinstance(need_gallery_info, str):
                need_gallery_info = need_gallery_info.lower() in ['true', '1', 'yes']
            need_gallery_info = bool(need_gallery_info)
        except (ValueError, TypeError):
            return jsonify({"status": "error", "error": "Invalid Parameter", "message": "need_gallery_info must be a boolean.", "code": "INVALID_GALLERY_PARAM"}), 400

        try:
            call_sign_src_int = int(call_sign_src)
            if call_sign_src_int < 0:
                return jsonify({"status": "error", "error": "Invalid Parameter", "message": "call_sign_src must be non-negative.", "code": "INVALID_CALL_SIGN_SRC"}), 400
        except (ValueError, TypeError):
            return jsonify({"status": "error", "error": "Invalid Parameter", "message": "call_sign_src must be a valid integer.", "code": "INVALID_CALL_SIGN_FORMAT"}), 400

        token, server_url = get_login(server)
        if not token:
            return jsonify({"status": "error", "error": "Authentication Failed", "message": "Could not obtain auth token.", "code": "AUTH_FAILED"}), 401

        result = get_player_personal_show(server_url, token, uid_int, need_gallery_info, call_sign_src_int)

        if not result:
            return jsonify({"status": "error", "error": "Data Not Found", "message": f"No player data found for UID: {uid_int}", "code": "PLAYER_DATA_NOT_FOUND"}), 404

        return json.dumps(result, indent=2, ensure_ascii=False), 200, {'Content-Type': 'application/json; charset=utf-8'}

    except Exception as e:
        return jsonify({"status": "error", "error": "Internal Server Error", "message": "An unexpected error occurred.", "code": "INTERNAL_SERVER_ERROR"}), 500


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=False, host='0.0.0.0', port=port)
