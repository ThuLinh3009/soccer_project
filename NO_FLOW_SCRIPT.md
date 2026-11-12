# Kịch bản bình luận và system prompt cho luồng NO

> **Phiên bản kịch bản 1.0** (2026-11-12). Bản chốt để triển khai vào `no_flow_llm.py` và bộ xếp lịch (`commentary_timeline.py`).
> Các lựa chọn đã chốt mặc định ở **mục 0**. Muốn đổi thì sửa mục 0, các mục sau đổi theo.

---

## 0. Các lựa chọn đã chốt

| # | Câu hỏi | Chốt | Lý do |
|---|---|---|---|
| 1 | Ngôn ngữ | **Tiếng Anh** | Khớp câu của luồng YES (SoccerNet tiếng Anh) và giọng TTS. Đổi sang tiếng Việt: sửa dòng `Language` trong prompt |
| 2 | Lời chào theo giờ ("Good evening") | **Không**, dùng "Hello and welcome" | `date_local` của FIFA không chắc đúng múi giờ (Brazil – Norway ghi 16:00 nhưng có `Z`). Nói sai giờ thì người xem nhận ra ngay |
| 3 | Nhận xét, cảm xúc | **Cảm xúc có, nhận xét không** | Được: hào hứng khi có bàn thắng, căng thẳng cuối trận dựa trên tỉ số. Cấm: khen chê cầu thủ, chiến thuật, "đáng lẽ", "xứng đáng" |
| 4 | Câu số áo ("X wears number N") | **Bỏ từng câu riêng.** Gộp 3–4 cầu thủ một câu, tối đa 2 câu mỗi hiệp | Trước đây có tới 22 câu số áo mỗi trận, nghe như đọc danh sách |
| 5 | Hiệp phụ, luân lưu, nghỉ uống nước, VAR | **Có**, xem giai đoạn H, I và mục 1.3 | `events.csv` có `Delay` (nghỉ uống nước), `VAR`; trận knock-out có thể có hiệp phụ |
| 6 | Giới tính | Lấy từ `competition`: có chữ "Women" thì **she/her** | Trận Chelsea – Man City (WSL) là bóng đá nữ |

---

## 1. Kịch bản theo giai đoạn

Mỗi giai đoạn có **câu bắt buộc** (luôn nói, đúng thứ tự) và **câu tuỳ chọn** (chỉ nói khi còn khoảng trống).
Mốc thời gian lấy từ `events.csv` của FIFA (`Start Time`, `End Time`, `Delay`...) và mp4 của từng hiệp.

### 1.1. Bảng giai đoạn

| # | Giai đoạn (`PHASE`) | Khi nào | Câu bắt buộc (theo thứ tự) | Câu tuỳ chọn | Dữ liệu |
|---|---|---|---|---|---|
| A | `welcome`, `teams`, `stakes` | Từ giây 5 hiệp 1, trước sự kiện YES đầu tiên. Không đủ chỗ thì chen vào khoảng trống trong 5 phút đầu | **A1** Chào mừng: giải, vòng / vòng đấu, sân, thành phố<br>**A2** Hai đội + hai HLV (đội nhà trước)<br>**A3** Ý nghĩa trận đấu | Phong độ 5 trận, sơ đồ, đội trưởng, trọng tài, khán giả | `match_info`, `staff`, `facts` (intro, coaches, form...) |
| B | `live_news`, `score_update`, `background` | Hiệp 1, các khoảng trống giữa sự kiện YES | **B1** Tin nóng: bàn thắng, thẻ, thay người, phạt đền, VAR (≤ 30 giây sau khi xảy ra)<br>**B2** Nhắc tỉ số khoảng mỗi 10 phút | Đội hình, ghế dự bị, cầu thủ (gộp), khán giả | `events`, `facts` |
| C | `half_time` | Tại `End Time` hiệp 1 (ví dụ 45'+7') | **C1** Còi hết hiệp 1 + **tỉ số hiệp 1** + người ghi bàn (nếu có)<br>**C2** Mời khán giả ở lại xem hiệp 2 | (không) | `events`, `match_info.half_time_score` |
| D | `second_half` | Giây 5 của hiệp 2 | **D1** Hiệp 2 bắt đầu + nhắc tỉ số<br>**D2** Thay người trong giờ nghỉ (nếu có) | Đội nào cần gì (đang thua / đang hoà) | `events` |
| E | như B | Hiệp 2, các khoảng trống | như B1, B2 | như B, ưu tiên thông tin chưa nói ở hiệp 1 | như B |
| F | `late_game` | Phút 80' và khi vào bù giờ (phút 90') | **F1** Phút 80': "còn khoảng 10 phút" + tỉ số<br>**F2** Phút 90': đã vào bù giờ + tỉ số | (không) | `events` |
| G | `full_time` | Tại `End Time` hiệp 2 (hoặc hiệp phụ / luân lưu nếu có) | **G1** Còi kết thúc + **tỉ số chung cuộc**<br>**G2** Người ghi bàn cả trận<br>**G3** Ý nghĩa kết quả: đội đi tiếp (knock-out) hoặc 3 điểm / chia điểm (giải VĐQG)<br>**G4** Chào tạm biệt | (không) | `events`, `match_info.stage` |
| H | `extra_time` | Nếu có hiệp phụ: đầu hiệp phụ 1 và 2 | **H1** Hai đội phải đá hiệp phụ + tỉ số | (không) | `events` (half 3, 4) |
| I | `penalties` | Nếu có luân lưu: trước và sau loạt sút | **I1** Trận đấu phân định bằng luân lưu<br>**I2** Kết quả luân lưu + đội đi tiếp | (không) | `match_info.home_penalties` / `away_penalties` |

### 1.2. Quy tắc xếp lịch (code đảm bảo, không phải LLM)

1. **Câu bắt buộc luôn được nói.** Nếu trùng sự kiện YES thì lùi sang khoảng trống gần nhất, không bỏ.
2. **Tin nóng** (bàn, thẻ, thay người, phạt đền) được nói **trong vòng 30 giây** sau thời điểm FIFA ghi. Nhiều tin cùng lúc thì gộp một câu.
3. **Khoảng cách tối thiểu:** cách sự kiện YES phía trước 15 giây, cách sự kiện YES phía sau 10 giây, cách câu NO trước 45 giây.
4. **Không quá 2 câu liên tiếp cùng chủ đề** (ví dụ 2 câu đội hình liền nhau thì câu thứ 3 phải đổi chủ đề).
5. **Nhắc tỉ số:** khoảng mỗi 10 phút. Không nhắc lại nếu 3 phút trước vừa nói tỉ số.
6. **Chuyện bên lề** (khán giả, ghế dự bị, cầu thủ) chỉ nói trong khoảng trống ≥ 2 phút, và không nói trong 2 phút sau bàn thắng.
7. **Câu cầu thủ:** gộp 3–4 cầu thủ một câu, tối đa 2 câu mỗi hiệp.
8. **Kiểm tra câu LLM** trước khi dùng. Câu bị loại thì dùng **câu dự phòng** ở mục 4:
   - có con số không có trong tin nhắn (sai tỉ số, sai phút);
   - có tên người không có trong tin nhắn;
   - vượt giới hạn số từ;
   - có từ cấm: giờ trong ngày, thời tiết, "young", "veteran", "deserved"...

### 1.3. Sự kiện đặc biệt trong `events.csv`

| Sự kiện FIFA | Xử lý |
|---|---|
| `Delay` "hydration break" | Câu tuỳ chọn `background`: "A short break for the players to take on water." Không nói lý do khác |
| `VAR` | `live_news`: chỉ nói đúng `description` (ví dụ "Penalty given"). Không đoán tình huống |
| `Penalty Awarded` rồi `Penalty Goal` cùng phút | Gộp một câu `live_news` |
| `Own goal` | `live_news`: ghi rõ phản lưới, tỉ số mới |
| `Goal!` + `Assist` | Gộp: người ghi bàn + người kiến tạo |

---

## 2. System prompt (đặt một lần trong agent ElevenLabs)

```text
You are the lead TV commentator of a live football broadcast. A second voice describes the action on the pitch.
Your job is to say the key lines of the broadcast (welcome, half-time, second half, late game, full-time)
and to fill the quiet moments with the information you are given.

Each message gives you:
PHASE, GENDER, MATCH, MINUTE, SCORE, FACT (what to say), LAST EVENT (what just happened on the pitch),
ALREADY SAID (your recent lines), and sometimes NEXT ROUND, POINTS or SCORERS.
Answer with the line to be spoken, nothing else.

Language: English. Spoken, natural, live broadcast style.

Hard rules:
1. Use only the information in the message. Never invent names, numbers, statistics, records, injuries,
   quotes, weather, time of day, crowd reactions or actions on the pitch.
2. The SCORE in the message is always right. Never say any other score. Say scores as "Brazil 1, Norway 2"
   or "Norway lead 2-1".
3. Say the minute only if it is in the FACT, and exactly as written there.
4. You cannot see the pitch. Never describe passes, shots, saves, chances or pressure unless they are
   in the FACT or the LAST EVENT.
5. Length: one or two sentences, at most 30 words. PHASE welcome and full_time: at most 45 words.
6. Do not repeat the wording of ALREADY SAID. Start each line in a different way.
7. Emotion is allowed: excitement for a goal, tension when time is running out.
   Opinions are not: never judge players, tactics, the referee or who deserves to win.
8. GENDER women: players are she/her. GENDER men: he/him.
9. No quotes, emojis, markdown, hashtags, stage directions or speaker names.

Phase rules:
- welcome: greet the viewers ("Hello and welcome"), then name the competition, the stage or matchday,
  the stadium and the city. Do not say good morning, afternoon or evening.
- teams: introduce both teams and their head coaches, home team first.
- stakes: say what is at stake, only from the FACT (knockout round, matchday, table position, form).
- live_news: a goal, card, substitution, penalty or VAR decision just happened. Say it right away.
  For a goal: excited, the scorer, the minute from the FACT and the new SCORE.
  For cards and substitutions: neutral, short.
- score_update: remind the score in a fresh way, short.
- background: one piece of background from the FACT, calm tone.
- half_time: the referee has blown for half-time. Give the half-time SCORE and the SCORERS if any,
  then invite the viewers to stay for the second half.
- second_half: the second half is under way. Remind the SCORE. Mention half-time substitutions if in the FACT.
- late_game: about ten minutes are left, or stoppage time has begun. Build tension with the SCORE.
- extra_time: the match goes to extra time. Give the SCORE.
- penalties: the match goes to a penalty shoot-out, or the shoot-out is over. Use only the FACT.
- full_time: the final whistle. Give the final SCORE, the SCORERS, what the result means
  (NEXT ROUND or POINTS from the message), then say goodbye to the viewers.
```

---

## 3. Mẫu tin nhắn gửi cho LLM mỗi lượt

Code tạo tin nhắn này. Các trường code tính sẵn để LLM **không phải suy luận**: `SCORE`, `MINUTE`, `SCORERS`, `NEXT ROUND`, `POINTS`, `GENDER`.

### 3.1. Giai đoạn mở đầu (A1)
```text
PHASE: welcome
GENDER: men
MATCH: Brazil v Norway, FIFA World Cup 2026, Round of 16, New York/New Jersey Stadium, New Jersey
MINUTE: 1' (kick-off)
SCORE: Brazil 0, Norway 0
FACT: Welcome to New York/New Jersey Stadium (New Jersey) for this FIFA World Cup match between Brazil and Norway, Round of 16.
LAST EVENT: none
ALREADY SAID: none
YOUR LINE:
```

### 3.2. Tin nóng (B1, bàn thắng)
```text
PHASE: live_news
GENDER: men
MATCH: Brazil v Norway, FIFA World Cup 2026, Round of 16
MINUTE: 79'
SCORE: Brazil 0, Norway 1
FACT: Goal! Erling Haaland scores for Norway in the 79th minute. Brazil 0, Norway 1.
LAST EVENT: a cross into the box, cleared by the defence.
ALREADY SAID: Change for Norway: Fredrik Aursnes on for Julian Ryerson. | Still goalless, Brazil 0, Norway 0.
YOUR LINE:
```

### 3.3. Hết hiệp 1 (C1 + C2)
```text
PHASE: half_time
GENDER: men
MATCH: Brazil v Norway, FIFA World Cup 2026, Round of 16
MINUTE: 45'+7' (end of the first half)
SCORE: Brazil 0, Norway 0
SCORERS: none
FACT: At half-time it is Brazil 0, Norway 0.
LAST EVENT: a corner, cleared by the defence.
ALREADY SAID: Marquinhos wears the captain's armband for Brazil. | Still goalless here.
YOUR LINE:
```

### 3.4. Hết trận (G1 → G4)
```text
PHASE: full_time
GENDER: men
MATCH: Brazil v Norway, FIFA World Cup 2026, Round of 16, New York/New Jersey Stadium, New Jersey
MINUTE: 90'+12' (final whistle)
SCORE: Brazil 1, Norway 2
SCORERS: Erling Haaland 79', 90' (Norway); Neymar Jr 90'+10' penalty (Brazil)
NEXT ROUND: Norway go through to the quarter-finals. Brazil are out.
FACT: Full-time: Brazil 1, Norway 2.
LAST EVENT: Neymar Jr scores from the penalty spot.
ALREADY SAID: Into stoppage time, Norway lead 2-0. | Neymar Jr is shown a yellow card.
YOUR LINE:
```

Giải VĐQG thì thay `NEXT ROUND` bằng `POINTS`, ví dụ `POINTS: Chelsea take the three points on matchday 1.` Trận hoà: `POINTS: The points are shared.`

**Cách code tính `NEXT ROUND`:** `stage` → vòng sau theo thứ tự Round of 32 → Round of 16 → Quarter-final → Semi-final → Final. Đội thắng lấy theo tỉ số (hoặc luân lưu nếu hoà). Nếu `stage` là "Final" thì `NEXT ROUND: <đội thắng> are the champions.`

---

## 4. Câu dự phòng và câu mong đợi (trận Brazil 1–2 Norway)

Số liệu thật từ `facts.csv` / `events.csv`. Cột "LLM mong đợi" là mẫu để so chất lượng, không phải câu cố định.

| Mã | Thời điểm | Câu dự phòng (khi LLM lỗi) | LLM mong đợi (ví dụ) |
|---|---|---|---|
| A1 | 1 - 00:05 | Hello and welcome to New York/New Jersey Stadium for this FIFA World Cup Round of 16 match between Brazil and Norway. | Hello and welcome to the New York/New Jersey Stadium, where Brazil and Norway meet in the Round of 16 of the World Cup. |
| A2 | sau A1 | It is Carlo Ancelotti's Brazil against Ståle Solbakken's Norway. | Carlo Ancelotti's Brazil take on Ståle Solbakken's Norway. |
| A3 | sau A2 | This is a knockout match: the winner goes through to the quarter-finals. | It's knockout football now: win, and you're in the quarter-finals. |
| B (tuỳ chọn) | khoảng trống | Brazil's last 5 results: W D W W W. | Brazil come in with four wins from their last five, most recently 2-1 against Japan. |
| B (nghỉ) | 1 - 27:00 | A short break for the players to take on water. | A brief pause here as the players take on water. |
| C1+C2 | 1 - 52:00 (45'+7') | The referee blows for half-time. Brazil 0, Norway 0. Stay with us for the second half. | There's the half-time whistle, Brazil 0, Norway 0. Stay with us, the second half is coming up. |
| D1 | 2 - 00:05 | The second half is under way. Brazil 0, Norway 0. | We're back under way for the second half, still goalless. |
| B1 | 2 - 13:00 | Change for Brazil in the 58th minute: Endrick comes on for Matheus Cunha. | A change for Brazil: Endrick replaces Matheus Cunha. |
| B1 | 2 - 34:00 | Goal! Erling Haaland scores for Norway in the 79th minute. Brazil 0, Norway 1. | Goal for Norway! Erling Haaland in the 79th minute, and it's Brazil 0, Norway 1! |
| F1 | 2 - 35:00 (80') | About ten minutes left. Brazil 0, Norway 1. | Ten minutes to go and Norway lead 1-0. |
| F2 | 2 - 45:00 (90') | We are into stoppage time. Brazil 0, Norway 2. | Into stoppage time now, and Norway lead 2-0. |
| B1 | 2 - 55:00 | Goal! Neymar Jr scores for Brazil from the penalty spot. Brazil 1, Norway 2. | Neymar Jr scores the penalty! Brazil 1, Norway 2, and we're deep into stoppage time. |
| G1+G2 | 2 - 57:00 (90'+12') | Full-time: Brazil 1, Norway 2. Goals from Erling Haaland (2) and Neymar Jr. | That's full-time! Brazil 1, Norway 2, with two goals from Erling Haaland and a late penalty from Neymar Jr. |
| G3+G4 | sau G1 | Norway go through to the quarter-finals. Thank you for joining us. | Norway are into the World Cup quarter-finals. Thanks for watching, and goodbye from New Jersey. |

Ví dụ câu **bị loại** (bộ kiểm tra ở mục 1.2, quy tắc 8):

| Câu LLM | Lý do bị loại |
|---|---|
| "Good evening and welcome to New Jersey..." | Có giờ trong ngày |
| "Haaland, the young striker, scores again!" | Từ cấm "young" (thông tin không có trong tin nhắn) |
| "Norway lead 3-1 now." | Tỉ số khác `SCORE` |
| "Brazil deserved more today." | Nhận xét (vi phạm hard rule 7) |

---

## 5. Triển khai vào code (sau khi duyệt)

| File | Việc làm |
|---|---|
| `no_flow_llm.py` | Thay `SYSTEM_PROMPT` bằng mục 2. Tin nhắn thêm `PHASE`, `GENDER`, `SCORERS`, `NEXT ROUND` / `POINTS` theo mục 3. Bộ kiểm tra: tên người lạ, từ cấm, giới hạn từ theo phase |
| `commentary_timeline.py` | Thêm các mốc bắt buộc A, C, D, F, G (H, I nếu có) vào lịch trước khi rải câu nền. Áp quy tắc 1.2 (2 câu cùng chủ đề, tỉ số mỗi 10 phút, gộp câu cầu thủ) |
| `match_facts.py` | Tạo fact gộp cầu thủ (3–4 người / câu), fact `Delay`, `VAR`, và câu dự phòng cho từng phase |

Sau khi triển khai: chạy với `--llm template` (không tốn credit) để kiểm tra lịch câu, rồi mới chạy `--llm elevenlabs`.
