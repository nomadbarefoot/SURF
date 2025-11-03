#!/bin/bash
BASE="http://localhost:6660"

# Login
TOKEN=$(curl -s -X POST $BASE/auth/login -H "Content-Type: application/json" -d '{"username":"testuser","password":"testpass123"}' | python3 -c "import sys, json; print(json.load(sys.stdin)['access_token'])")
SESSION=$(curl -s -X POST $BASE/sessions/ -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d '{}' | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('session_id'))")

echo "Testing obscure government sites from small countries..."
echo "Session: $SESSION"
echo ""

sites=(
  "Tuvalu|https://www.gov.tv"
  "Palau|https://www.palaugov.pw"
  "Liechtenstein|https://www.llv.li"
  "Monaco|https://www.gouv.mc"
  "San Marino|https://www.governo.sm"
  "Andorra|https://www.govern.ad"
  "Vanuatu|https://www.gov.vu"
)

for site_info in "${sites[@]}"; do
  IFS='|' read -r country url <<< "$site_info"
  echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
  echo "📍 $country ($url)"
  echo ""
  
  # Navigate
  NAV=$(curl -s -X POST $BASE/browser/navigate -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"session_id\":\"$SESSION\",\"url\":\"$url\",\"wait_until\":\"networkidle\",\"timeout\":45000}")
  SUCCESS=$(echo "$NAV" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('success', False))" 2>/dev/null || echo "False")
  
  if [ "$SUCCESS" = "True" ]; then
    FINAL_URL=$(echo "$NAV" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('data',{}).get('url','N/A')[:70])" 2>/dev/null || echo "N/A")
    STATUS=$(echo "$NAV" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('data',{}).get('status','N/A'))" 2>/dev/null || echo "N/A")
    TITLE=$(echo "$NAV" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('data',{}).get('title','N/A')[:60])" 2>/dev/null || echo "N/A")
    
    echo "✅ Navigation: SUCCESS"
    echo "   Final URL: $FINAL_URL"
    echo "   Status: $STATUS"
    echo "   Title: $TITLE"
    echo ""
    
    sleep 2
    
    # Extract title
    EXT=$(curl -s -X POST $BASE/browser/extract -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"session_id\":\"$SESSION\",\"extract_type\":\"text\",\"selector\":\"title\"}")
    TITLE_TEXT=$(echo "$EXT" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('data',{}).get('content','N/A')[:80])" 2>/dev/null || echo "N/A")
    echo "   Page Title: $TITLE_TEXT"
    
    # Extract links
    sleep 1
    LINKS=$(curl -s -X POST $BASE/browser/extract -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" -d "{\"session_id\":\"$SESSION\",\"extract_type\":\"links\"}")
    LINK_COUNT=$(echo "$LINKS" | python3 -c "import sys, json; d=json.load(sys.stdin); links=d.get('data',{}).get('content',[]); print(len(links) if isinstance(links, list) else 0)" 2>/dev/null || echo "0")
    echo "   Links found: $LINK_COUNT"
    
    if [ "$LINK_COUNT" -gt 0 ] && [ "$LINK_COUNT" -lt 20 ]; then
      echo "   Sample links:"
      echo "$LINKS" | python3 -c "import sys, json; d=json.load(sys.stdin); links=d.get('data',{}).get('content',[]); [print(f\"     - {l.get('text','')[:40]} {l.get('url','')[:50]}\") for l in links[:3]]" 2>/dev/null
    fi
    
  else
    ERROR=$(echo "$NAV" | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('detail','Unknown error')[:100])" 2>/dev/null || echo "Failed to parse error")
    echo "❌ Navigation: FAILED"
    echo "   Error: $ERROR"
  fi
  
  echo ""
  sleep 1
done

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "Cleaning up session..."
curl -s -X DELETE $BASE/sessions/$SESSION -H "Authorization: Bearer $TOKEN" > /dev/null
echo "Done!"
