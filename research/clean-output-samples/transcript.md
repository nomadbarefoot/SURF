# youtube_transcript sample

Served by: deployed `surf` docker container (127.0.0.1:17777)

Tool: `POST /youtube/transcript`

Request: `{"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "max_text_length": 1500}`

Response bytes (pretty JSON): 2598

## Exact payload delivered to the agent

```json
{
  "success": true,
  "video": {
    "id": "dQw4w9WgXcQ",
    "url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "title": "Rick Astley - Never Gonna Give You Up (Official Video) (4K Remaster)",
    "channel": "Rick Astley",
    "duration_seconds": 213,
    "upload_date": "20091025"
  },
  "track": {
    "language_code": "en",
    "language_name": "English",
    "source": "manual"
  },
  "content": "[00:00:01] [♪♪♪]\n[00:00:18] ♪ We're no strangers to love ♪\n[00:00:22] ♪ You know the rules and so do I ♪\n[00:00:27] ♪ A full commitment's what I'm thinking of ♪\n[00:00:31] ♪ You wouldn't get this from any other guy ♪\n[00:00:35] ♪ I just wanna tell you how I'm feeling ♪\n[00:00:40] ♪ Gotta make you understand ♪\n[00:00:43] ♪ Never gonna give you up ♪\n[00:00:45] ♪ Never gonna let you down ♪\n[00:00:47] ♪ Never gonna run around and desert you ♪\n[00:00:51] ♪ Never gonna make you cry ♪\n[00:00:53] ♪ Never gonna say goodbye ♪\n[00:00:55] ♪ Never gonna tell a lie and hurt you ♪\n[00:01:00] ♪ We've known each other for so long ♪\n[00:01:04] ♪ Your heart's been aching but you're too shy to say it ♪\n[00:01:09] ♪ Inside we both know what's been going ♪\n[00:01:13] ♪ We know the game and we're gonna play it ♪\n[00:01:17] ♪ And if you ask me how I'm feeling ♪\n[00:01:22] ♪ Don't tell me you're too blind to see ♪\n[00:01:25] ♪ Never gonna give you up ♪\n[00:01:27] ♪ Never gonna let you down ♪\n[00:01:29] ♪ Never gonna run around and desert you ♪\n[00:01:33] ♪ Never gonna make you cry ♪\n[00:01:35] ♪ Never gonna say goodbye ♪\n[00:01:38] ♪ Never gonna tell a lie and hurt you ♪\n[00:01:42] ♪ Never gonna give you up ♪\n[00:01:44] ♪ Never gonna let you down ♪\n[00:01:46] ♪ Never gonna run around and desert you ♪\n[00:01:50] ♪ Never gonna make you cry ♪\n[00:01:52] ♪ Never gonna say goodbye ♪\n[00:01:54] ♪ Never gonna tell a lie and hurt you ♪\n[00:01:59] ♪ (Ooh, give you up) ♪\n[00:02:08] ♪ Never gonna give, never go\n\n[Transcript truncated; use artifact for full text.]",
  "truncated": true,
  "artifact": {
    "download_id": "dl_d63ce8a25bfe",
    "filename": "dQw4w9WgXcQ-en-transcript.md",
    "path": "data/downloads/dl_d63ce8a25bfe_dQw4w9WgXcQ-en-transcript.md",
    "absolute_path": "/app/data/downloads/dl_d63ce8a25bfe_dQw4w9WgXcQ-en-transcript.md",
    "external": false,
    "source_url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
    "created_at_epoch": 1785191641.3835733,
    "size_bytes": 3226,
    "content_type": "text/markdown; charset=utf-8",
    "created_at": "2026-07-27T22:34:01Z",
    "content_url": "/downloads/dl_d63ce8a25bfe/content"
  }
}
```
