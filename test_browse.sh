#!/bin/bash
BASE="http://localhost:6660"

# Login
echo "1. Logging in..."
TOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"testuser","password":"testpass123"}' | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
echo "✓ Token obtained"

# Create session
echo "2. Creating session..."
SESSION_RESP=$(curl -s -X POST $BASE/sessions/ -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}')
SESSION=$(echo "$SESSION_RESP" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('session_id','ERROR')); sys.exit(0 if d.get('success') else 1)" 2>&1)
if [ $? -ne 0 ]; then
    echo "❌ Session creation failed:"
    echo "$SESSION_RESP" | python3 -m json.tool
    exit 1
fi
echo "✓ Session: $SESSION"

# Wait a moment
sleep 1

# Test with example.com first
echo "3. Navigating to example.com..."
NAV1=$(curl -s -X POST $BASE/browser/navigate -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"session_id\":\"$SESSION\",\"url\":\"https://example.com\",\"wait_until\":\"networkidle\",\"timeout\":30000}")
echo "$NAV1" | python3 -c "import sys, json; d=json.load(sys.stdin); print('Success:', d.get('success')); print('Error:', d.get('detail','None')); print('Status:', d.get('data',{}).get('status','N/A'))"

sleep 2

# Extract
echo "4. Extracting content..."
EXT1=$(curl -s -X POST $BASE/browser/extract -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"session_id\":\"$SESSION\",\"extract_type\":\"text\",\"selector\":\"h1\"}")
echo "$EXT1" | python3 -c "import sys, json; d=json.load(sys.stdin); c=d.get('data',{}).get('content',''); print('Content:', c[:150]); print('Length:', len(c))"

# Now test obscure sites
echo ""
echo "5. Testing obscure government sites..."
echo "   a) Tuvalu (gov.tv)..."
NAV2=$(curl -s -X POST $BASE/browser/navigate -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"session_id\":\"$SESSION\",\"url\":\"https://www.gov.tv\",\"wait_until\":\"networkidle\",\"timeout\":45000}")
echo "$NAV2" | python3 -c "import sys, json; d=json.load(sys.stdin); print('      Success:', d.get('success')); print('      URL:', d.get('data',{}).get('url','N/A')[:70]); print('      Status:', d.get('data',{}).get('status','N/A'))"

sleep 3
EXT2=$(curl -s -X POST $BASE/browser/extract -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"session_id\":\"$SESSION\",\"extract_type\":\"text\",\"selector\":\"title\"}")
echo "$EXT2" | python3 -c "import sys, json; d=json.load(sys.stdin); print('      Title:', d.get('data',{}).get('content','N/A')[:80])"

echo ""
echo "   b) Palau (palaugov.pw)..."
NAV3=$(curl -s -X POST $BASE/browser/navigate -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"session_id\":\"$SESSION\",\"url\":\"https://www.palaugov.pw\",\"wait_until\":\"networkidle\",\"timeout\":45000}")
echo "$NAV3" | python3 -c "import sys, json; d=json.load(sys.stdin); print('      Success:', d.get('success')); print('      Final URL:', d.get('data',{}).get('url','N/A')[:70])"

sleep 3
EXT3=$(curl -s -X POST $BASE/browser/extract -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"session_id\":\"$SESSION\",\"extract_type\":\"links\",\"selector\":\"a\"}")
echo "$EXT3" | python3 -c "import sys, json; d=json.load(sys.stdin); links=d.get('data',{}).get('content',[]); print('      Links:', len(links)); [print(f\"        - {l.get('text','')[:40]} {l.get('href','')[:50]}\") for l in links[:4]]"

echo ""
echo "6. Cleanup..."
curl -s -X DELETE $BASE/sessions/$SESSION -H "Authorization: Bearer $TOKEN" | python3 -c "import sys, json; d=json.load(sys.stdin); print('Closed:', d.get('success','N/A'))"
