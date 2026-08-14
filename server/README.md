# ⚡ MirrorPro — Premium Mirror Server

স্লো সার্ভারের লিংক দাও → তোমার সার্ভার ১৬ কানেকশনে ফাস্টেস্ট ডাউনলোড করবে → ডাইরেক্ট মিরর লিংক পাবে।

## 🚀 Railway Deploy

1. Railway তে এই রিপো কানেক্ট করো
2. Variables সেট করো:
   - `API_KEY` — যেকোনো র‍্যান্ডম স্ট্রিং (খালি = auth বন্ধ)
   - `FILE_TTL` — সেকেন্ডে অটো-ডিলিট (`0` = কখনো ডিলিট না)
   - `RPC_SECRET` — aria2 RPC সিক্রেট
   - `MAX_CONCURRENT` — একসাথে কয়টা ডাউনলোড
   - `SERVER_NAME` — ডিসপ্লে নাম
3. Deploy → URL পাবে

## 📡 API

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/api/mirror` | নতুন মিরর শুরু |
| GET | `/api/status/{gid}` | প্রগ্রেস চেক |
| GET | `/api/list` | সব টাস্ক |
| DELETE | `/api/delete/{gid}` | টাস্ক ডিলিট |
| GET | `/api/qr?url=` | QR কোড |
| GET | `/d/{filename}` | ফাইল ডাউনলোড |
| GET | `/health` | সার্ভার হেলথ |
| GET | `/` | ওয়েব UI |
| GET | `/dashboard` | ড্যাশবোর্ড |
| GET | `/status/{gid}` | ওয়েব স্ট্যাটাস পেজ |
