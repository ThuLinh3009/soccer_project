# Kịch bản bình luận chung cho luồng NO (dùng cho mọi trận)

> **Kịch bản 2.0** (2026-11-12), đã đưa vào code ở v5.0 (`script_v2.py`, `no_flow_v2.py`). Bộ khuôn câu dùng chung cho **mọi trận đấu**. Mỗi câu có các chỗ trống `{biến}`. Code điền tự động từ metadata FIFA (`match_info.csv`, `staff.csv`, `events.csv`, `standings_before.csv`, `form.csv`, `lineups.csv`).
> Mỗi câu bắt buộc có nhiều **biến thể** theo loại trận (giải VĐQG / vòng bảng / knock-out / chung kết) và theo tỉ số (hoà / dẫn 1 bàn / dẫn nhiều bàn).
> Khuôn câu được dùng theo 2 cách:
> 1. **Câu dự phòng:** khi LLM lỗi, code dùng thẳng khuôn đã điền biến.
> 2. **Gợi ý cho LLM:** khuôn đã điền biến được gửi trong trường `FACT`, LLM nói lại tự nhiên hơn và không lặp từng chữ.

---

## 0. Các lựa chọn đã chốt

| # | Câu hỏi | Chốt |
|---|---|---|
| 1 | Ngôn ngữ | Tiếng Anh (khớp luồng YES). Muốn tiếng Việt thì dịch các khuôn ở mục 2 và đổi dòng `Language` trong prompt |
| 2 | Chào theo giờ ("Good evening") | Không. Dùng "Hello and welcome" (giờ địa phương trong dữ liệu FIFA không chắc đúng) |
| 3 | Cảm xúc / nhận xét | Có cảm xúc (bàn thắng, cuối trận), không nhận xét (khen chê cầu thủ, trọng tài, "xứng đáng") |
| 4 | Câu cầu thủ | Gộp 3–4 cầu thủ một câu, tối đa 2 câu mỗi hiệp |
| 5 | Giới tính | `competition` có chữ "Women" thì cầu thủ là she/her |

---

## 1. Biến (code điền từ metadata)

### 1.1. Biến lấy thẳng từ file

| Biến | Nguồn | Ví dụ (WSL) | Ví dụ (World Cup) |
|---|---|---|---|
| `{competition}` | `match_info.competition` (bỏ ký hiệu ™) | Women's Super League | FIFA World Cup |
| `{season}` | `match_info.season` | Women's Super League 2025/2026 | FIFA World Cup 2026 |
| `{stage}` | `match_info.stage` | Regular Season | Round of 16 |
| `{group}` | `match_info.group` | (trống) | (trống) |
| `{matchday}` | `match_info.matchday` | 1 | (trống) |
| `{stadium}` | `match_info.stadium` | Stamford Bridge | New York/New Jersey Stadium |
| `{city}` | `match_info.city` | London | New Jersey |
| `{attendance}` | `match_info.attendance`, có dấu phẩy nghìn | 14,182 | 80,663 |
| `{capacity}` | `match_info.capacity` | 40,044 | (trống) |
| `{stadium_built}` | `match_info.stadium_built` | 1877 | (trống) |
| `{referee}` | `match_info.referee` | Emily Heaslip | Ismail Elfath |
| `{home_team}`, `{away_team}` | `match_info.home_team`, `away_team` | Chelsea, Manchester City | Brazil, Norway |
| `{home_tactics}`, `{away_tactics}` | `match_info.home_tactics`, `away_tactics` | 3-4-2-1, 4-2-3-1 | 4-1-2-3, 4-1-2-3 |
| `{home_coach}`, `{away_coach}` | `staff.csv`, `role = head_coach` | Sonia Bompastor, Andrée Alexander Jeglertz | Carlo Ancelotti, Ståle Solbakken |
| `{home_captain}`, `{away_captain}` | `lineups.csv`, `captain = True` | Millie Bright, … | Marquinhos, Martin Odegaard |

### 1.2. Biến code tính sẵn

| Biến | Cách tính | Ví dụ |
|---|---|---|
| `{matchday_word}` | `matchday` viết bằng chữ: 1 → one, 2 → two, … 38 → thirty-eight | one |
| `{round_phrase}` | Có `matchday` → "matchday {matchday_word}"; có `group` → "Group {group}"; còn lại → `{stage}` | matchday one / Group C / Round of 16 |
| `{match_kind}` | `league` (có matchday), `group` (có group), `final` (stage = Final), `knockout` (còn lại) | league / knockout |
| `{next_stage}` | Vòng sau của `{stage}`: Round of 32 → Round of 16 → quarter-finals → semi-finals → Final | quarter-finals |
| `{minute}` | Theo kiểu FIFA: phút 1–45, 45'+x, 46–90, 90'+x | 79', 45'+7' |
| `{home_goals}`, `{away_goals}` | Đếm bàn thắng trong `events.csv` tới thời điểm câu được nói | 0, 1 |
| `{score}` | "{home_team} {home_goals}, {away_team} {away_goals}" | Brazil 0, Norway 1 |
| `{leader}`, `{trailer}` | Đội đang dẫn / đang bị dẫn (trống nếu hoà) | Norway, Brazil |
| `{lead_score}` | "{bàn đội dẫn}-{bàn đội bị dẫn}" | 1-0 |
| `{margin}` | Cách biệt bàn thắng | 1 |
| `{ht_score}` | Tỉ số hết hiệp 1, dạng `{score}` | Chelsea 1, Manchester City 0 |
| `{scorers}` | Danh sách người ghi bàn: "Name minute' (team)", gộp người ghi 2 bàn, ghi chú "pen" / "og" | Erling Haaland 79', 90' (Norway); Neymar Jr 90'+10' pen (Brazil) |
| `{winner}`, `{loser}` | Theo tỉ số cuối (hoặc luân lưu) | Norway, Brazil |
| `{home_form}` | 5 trận gần nhất từ `form.csv`, ví dụ "W D W W W" | W D W W W |
| `{home_wins_last5}` | Số trận thắng trong 5 trận gần nhất | 4 |
| `{home_position}`, `{home_points}` | `standings_before.csv` (hạng viết dạng thứ tự: 1st, 2nd…) | 3rd, 7 |
| `{h2h_count}`, `{h2h_home_wins}`, `{h2h_away_wins}`, `{h2h_draws}` | `head_to_head.csv` | 12, 8, 2, 2 |
| `{pronoun}` | he / she theo giới tính | she |

**Quy tắc khi thiếu dữ liệu:** khuôn câu nào cần biến bị trống thì **bỏ khuôn đó** và dùng biến thể khác hoặc bỏ câu. Không bao giờ nói "unknown" hay để trống. Ví dụ không có `{city}` thì dùng biến thể không có thành phố. Không có HLV thì A2 dùng biến thể không có HLV.

---

## 2. Khuôn câu theo giai đoạn

Mỗi mục ghi rõ **khi nào nói** và **điều kiện chọn biến thể**. Có nhiều biến thể cùng điều kiện thì code chọn ngẫu nhiên (cố định theo `seed`) để các trận không nghe giống hệt nhau.

### A. Mở đầu trận (bắt buộc, từ giây 5 của hiệp 1, theo thứ tự A1 → A2 → A3)

**A1. Chào mừng**

| Điều kiện | Khuôn câu |
|---|---|
| `league` | Hello and welcome to {stadium} in {city} for this {competition} matchday {matchday_word} clash between {home_team} and {away_team}. |
| `league` | Welcome to {stadium}, {city}, where {home_team} host {away_team} on matchday {matchday_word} of the {competition}. |
| `group` | Hello and welcome to {stadium} in {city} for this {competition} Group {group} match between {home_team} and {away_team}. |
| `knockout` | Hello and welcome to {stadium} in {city} for this {competition} {stage} tie between {home_team} and {away_team}. |
| `knockout` | Welcome to {stadium}, {city}: it's {home_team} against {away_team} in the {stage} of the {competition}. |
| `final` | Hello and welcome to {stadium} in {city} for the {competition} Final between {home_team} and {away_team}. |
| thiếu `{city}` | Hello and welcome to {stadium} for this {competition} {round_phrase} match between {home_team} and {away_team}. |

**A2. Hai đội và HLV**

| Điều kiện | Khuôn câu |
|---|---|
| có 2 HLV | It's {home_coach}'s {home_team} against {away_coach}'s {away_team}. |
| có 2 HLV | {home_team}, led by {home_coach}, take on {away_coach}'s {away_team}. |
| thiếu HLV | {home_team} take on {away_team}. |

**A3. Ý nghĩa trận đấu**

| Điều kiện | Khuôn câu |
|---|---|
| `knockout` | It's knockout football: the winner goes through to the {next_stage}. |
| `knockout` | Win today and you're in the {next_stage}; lose and you go home. |
| `final` | One game for the trophy: the winner is crowned {competition} champion. |
| `group` có bảng xếp hạng | {home_team} have {home_points} points in Group {group}, {away_team} have {away_points}. |
| `league`, matchday 1 | It's the opening day of the season, and both sides want to start with three points. |
| `league` có bảng xếp hạng | {home_team} start the day {home_position} on {home_points} points, {away_team} are {away_position} on {away_points}. |

**Tuỳ chọn ở đầu trận** (nói trong các khoảng trống của 15 phút đầu, mỗi câu một lần):

| Chủ đề | Khuôn câu |
|---|---|
| Phong độ | {home_team} have won {home_wins_last5} of their last five games. |
| Phong độ | {away_team}'s last five results read {away_form}. |
| Đối đầu | These two sides have met {h2h_count} times: {h2h_home_wins} wins for {home_team}, {h2h_away_wins} for {away_team} and {h2h_draws} draws. |
| Sơ đồ | {home_team} line up in a {home_tactics}, {away_team} in a {away_tactics}. |
| Đội trưởng | {home_captain} captains {home_team}, {away_captain} leads {away_team}. |
| Trọng tài | {referee} is the referee today. |
| Khán giả | The attendance today is {attendance}. |
| Sân | {stadium}, built in {stadium_built}, holds {capacity} spectators. |

### B. Trong hiệp 1 và E. Trong hiệp 2

**B1. Tin nóng** (bắt buộc, trong vòng 30 giây sau thời điểm FIFA ghi trong `events.csv`)

| Sự kiện FIFA | Khuôn câu |
|---|---|
| `Goal!` | Goal! {player} scores for {team} in the {minute_ordinal} minute. {score}. |
| `Goal!` + `Assist` | Goal for {team}! {player} scores, set up by {assist_player}. {score}. |
| `Own goal` | An own goal from {player}, and it counts for {benefit_team}. {score}. |
| `Penalty Goal` | {player} scores from the penalty spot for {team}. {score}. |
| `Penalty Awarded` | Penalty to {team}! |
| `Penalty Missed` / `Attempt Missed` sau phạt đền | {player} misses the penalty! It stays {score}. |
| `Yellow card` | {player} ({team}) is shown a yellow card. |
| `Red card` | {player} is sent off! {team} are down to ten. |
| `Second yellow` | A second yellow for {player}, and {pronoun} is off. {team} are down to ten. |
| `Substitution` | Change for {team}: {player_in} comes on for {player_off}. |
| 2 thay người cùng phút | Double change for {team}: {player_in_1} replaces {player_off_1}, and {player_in_2} replaces {player_off_2}. |
| `VAR` | The referee goes to VAR: {var_description}. |
| `Delay` (uống nước) | A short break for the players to take on water. |

Nhiều sự kiện cùng phút (ví dụ phạt đền + bàn thắng) thì **gộp một câu**, ưu tiên bàn thắng.

**B2. Nhắc tỉ số** (bắt buộc khoảng mỗi 10 phút; không nhắc nếu 3 phút trước vừa nói tỉ số)

| Điều kiện | Khuôn câu |
|---|---|
| 0-0 | Still goalless here between {home_team} and {away_team}. |
| 0-0 | No goals yet: {score}. |
| hoà có bàn | All square at {lead_score}. |
| hoà có bàn | It's level, {score}. |
| dẫn 1 bàn | {leader} lead {lead_score}. |
| dẫn 1 bàn | {score}, {leader} just in front. |
| dẫn ≥ 2 bàn | {leader} are {margin} goals to the good, {score}. |

**Tuỳ chọn trong hiệp** (khoảng trống ≥ 2 phút, không nói trong 2 phút sau bàn thắng)

| Chủ đề | Khuôn câu |
|---|---|
| Đội hình (gộp) | In the {team} line-up: {player_1}, {player_2}, {player_3} and {player_4}. |
| Ghế dự bị | On the {team} bench: {bench_list}. |
| Số áo (gộp, tối đa 2 câu mỗi hiệp) | For {team}, {player_1} wears {n1}, {player_2} {n2} and {player_3} {n3}. |
| Thẻ đã có | {player} has already been booked. |

### C. Hết hiệp 1 (bắt buộc, tại `End Time` của hiệp 1)

**C1. Tỉ số hiệp 1**

| Điều kiện | Khuôn câu |
|---|---|
| 0-0 | The referee blows for half-time, and it's goalless: {score}. |
| 0-0 | Half-time here, no goals yet between {home_team} and {away_team}. |
| hoà có bàn | Half-time, and it's all square: {score}. |
| dẫn | That's half-time. {leader} lead {lead_score}. |
| dẫn | The whistle goes for the break with {leader} in front, {score}. |

**C1b. Người ghi bàn** (chỉ khi hiệp 1 có bàn)

| Điều kiện | Khuôn câu |
|---|---|
| có bàn | The goals so far: {scorers}. |
| 1 bàn | {scorer} with the only goal so far. |

**C2. Mời xem hiệp 2**

| Khuôn câu |
|---|
| Stay with us, the second half is coming up. |
| Don't go anywhere, we'll be back for the second half. |

### D. Bắt đầu hiệp 2 (bắt buộc, giây 5 của hiệp 2)

| Điều kiện | Khuôn câu |
|---|---|
| D1, luôn nói | The second half is under way. {score}. |
| D1, luôn nói | We're back under way for the second half, {score_phrase}. |
| D2, có thay người giờ nghỉ | {team} made a change at the break: {player_in} on for {player_off}. |

`{score_phrase}`: 0-0 → "still goalless"; hoà → "all square at {lead_score}"; dẫn → "{leader} lead {lead_score}".

### F. Cuối trận (bắt buộc)

**F1. Phút 80'**

| Điều kiện | Khuôn câu |
|---|---|
| hoà | Ten minutes to go, and it's still level: {score}. |
| dẫn 1 bàn | Ten minutes left. {leader} lead {lead_score}; can {trailer} find a reply? |
| dẫn ≥ 2 bàn | Ten minutes to go, and {leader} lead {lead_score}. |

**F2. Phút 90' (vào bù giờ)**

| Điều kiện | Khuôn câu |
|---|---|
| hoà | We're into stoppage time, and it's {score}. |
| dẫn 1 bàn | Into stoppage time: {leader} lead {lead_score}, and {trailer} are running out of time. |
| dẫn ≥ 2 bàn | Into stoppage time now, {score}. |

### G. Hết trận (bắt buộc, tại `End Time` của hiệp 2, hoặc của hiệp phụ / luân lưu nếu có, theo thứ tự G1 → G4)

**G1. Tỉ số chung cuộc**

| Điều kiện | Khuôn câu |
|---|---|
| thắng | That's full-time! {score}. |
| thắng | The final whistle goes: {winner} win {lead_score}. |
| hoà 0-0 | Full-time, and it finishes goalless: {score}. |
| hoà có bàn | Full-time, and the points are shared: {score}. |

**G2. Người ghi bàn** (chỉ khi có bàn)

| Khuôn câu |
|---|
| The goals: {scorers}. |

**G3. Ý nghĩa kết quả**

| Điều kiện | Khuôn câu |
|---|---|
| `knockout` | {winner} are through to the {next_stage}; {loser} are out. |
| `final` | {winner} are the {competition} champions! |
| `group` | {winner} take the three points in Group {group}. / Hoà: A point each in Group {group}. |
| `league` thắng | {winner} take the three points on matchday {matchday_word}. |
| `league` hoà | The points are shared on matchday {matchday_word}. |

**G4. Chào kết thúc**

| Khuôn câu |
|---|
| Thanks for joining us from {stadium}. Goodbye. |
| That's all from {city}. Thank you for watching, and goodbye. |

### H. Hiệp phụ (chỉ trận `knockout` / `final` hoà sau 90 phút)

| Khi | Khuôn câu |
|---|---|
| Hết hiệp 2 | It's {score} after ninety minutes, so we're going to extra time. |
| Đầu hiệp phụ 1 | Extra time is under way, {score}. |
| Đầu hiệp phụ 2 | Fifteen minutes left in extra time, {score}. |

### I. Luân lưu

| Khi | Khuôn câu |
|---|---|
| Hết hiệp phụ | Still {score} after extra time: this will be decided on penalties. |
| Hết luân lưu | {winner} win the shoot-out {winner_pens}-{loser_pens}! |

Sau I, nói G3 và G4 như bình thường.

---

## 3. Quy tắc xếp lịch (code đảm bảo, không phải LLM)

1. **Câu bắt buộc luôn được nói** (A1–A3, B1, B2, C1–C2, D1, F1, F2, G1–G4, và H, I nếu có). Nếu trùng sự kiện YES thì lùi sang khoảng trống gần nhất, không bỏ.
2. **Thứ tự cố định:** A1 → A2 → A3; C1 → C1b → C2; G1 → G2 → G3 → G4. Các câu trong một nhóm cách nhau tối đa 15 giây.
3. **Tin nóng** nói trong vòng 30 giây sau thời điểm FIFA ghi.
4. **Khoảng cách tối thiểu:** cách sự kiện YES trước 15 giây, cách sự kiện YES sau 10 giây, cách câu NO trước 45 giây (câu bắt buộc trong cùng nhóm thì không áp dụng).
5. **Không quá 2 câu liên tiếp cùng chủ đề.**
6. **Câu tuỳ chọn** chỉ nói trong khoảng trống ≥ 2 phút, không nói trong 2 phút sau bàn thắng, mỗi chủ đề tối đa 1 lần mỗi hiệp (số áo: 2 lần).
7. **Kiểm tra câu LLM.** Câu bị loại thì dùng khuôn câu đã điền biến:
   - có con số không có trong tin nhắn;
   - có tên người không có trong tin nhắn;
   - quá số từ;
   - có từ cấm: morning, afternoon, evening, tonight, weather, young, veteran, deserved...

---

## 4. System prompt (đặt một lần trong agent ElevenLabs, dùng cho mọi trận)

```text
You are the lead TV commentator of a live football broadcast. A second voice describes the action on the pitch.
Your job is to say the key lines of the broadcast (welcome, half-time, second half, late game, full-time)
and to fill the quiet moments with the information you are given.

Each message gives you:
PHASE, GENDER, MATCH, MINUTE, SCORE, FACT (what to say), LAST EVENT (what just happened on the pitch),
ALREADY SAID (your recent lines), and sometimes SCORERS, NEXT ROUND or POINTS.
Say the FACT as a live commentator would. Answer with the line to be spoken, nothing else.

Language: English. Spoken, natural, live broadcast style.

Hard rules:
1. Use only the information in the message. Never invent names, numbers, statistics, records, injuries,
   quotes, weather, time of day, crowd reactions or actions on the pitch.
2. The SCORE in the message is always right. Never say any other score.
3. Say a minute only if it is in the FACT, and exactly as written there.
4. You cannot see the pitch. Never describe passes, shots, saves, chances or pressure unless they are
   in the FACT or the LAST EVENT.
5. Length: one or two sentences, at most 30 words. PHASE welcome and full_time: at most 45 words.
6. Keep every name, team, number and score of the FACT. Change only the wording, and do not repeat
   the wording of ALREADY SAID.
7. Emotion is allowed: excitement for a goal, tension when time is running out.
   Opinions are not: never judge players, tactics, the referee or who deserves to win.
8. GENDER women: players are she/her. GENDER men: he/him.
9. No quotes, emojis, markdown, hashtags, stage directions or speaker names.
10. Say only what the FACT is about. Some moments are split into several lines said one after the other
   (score, scorers, invitation, result, goodbye): never add the content of another line, e.g. no goodbye
   and no invitation unless the FACT says it.

Phase rules:
- welcome: greet the viewers ("Hello and welcome"), name the stadium, the city, the competition,
  the round or matchday and both teams. Never say good morning, afternoon or evening.
- teams: introduce both teams and their head coaches, home team first.
- stakes: say what is at stake, only from the FACT.
- live_news: a goal, card, substitution, penalty or VAR decision just happened. Say it right away.
  Goal: excited, with the scorer and the new SCORE. Cards and substitutions: neutral and short.
- score_update: remind the score in a fresh way, short.
- background: one piece of background from the FACT, calm tone.
- half_time: one part of the half-time moment, the one in the FACT: the whistle and the score,
  or the scorers, or the invitation to stay for the second half.
- second_half: the second half is under way. Remind the SCORE.
- late_game: about ten minutes left, or stoppage time has begun. Build tension with the SCORE.
- extra_time: the match goes to extra time, or extra time is under way. Give the SCORE.
- penalties: the match goes to penalties, or the shoot-out is over. Use only the FACT.
- full_time: one part of the full-time moment, the one in the FACT: the final whistle and the score,
  or the scorers, or what the result means, or the goodbye.
```

---

## 5. Khuôn tin nhắn gửi cho LLM mỗi lượt

```text
PHASE: {phase}
GENDER: {men|women}
MATCH: {home_team} v {away_team}, {competition}, {round_phrase}, {stadium}, {city}
MINUTE: {minute}
SCORE: {score}
SCORERS: {scorers}                      (chỉ có ở half_time, full_time)
NEXT ROUND: {next_round_sentence}       (chỉ có ở full_time của knockout / final)
POINTS: {points_sentence}               (chỉ có ở full_time của league / group)
FACT: {khuôn câu ở mục 2 đã điền biến}
LAST EVENT: {câu YES gần nhất, đã bỏ [PLAYER]/[TEAM]} hoặc none
ALREADY SAID: {3 câu NO gần nhất, cách nhau bởi " | "} hoặc none
YOUR LINE:
```

`{next_round_sentence}`, ví dụ "{winner} go through to the {next_stage}. {loser} are out."
`{points_sentence}`, ví dụ "{winner} take the three points." hoặc "The points are shared."

---

## 6. Kiểm tra: cùng một khuôn, 2 trận khác nhau

| Mã | Chelsea 2–1 Man City (WSL, matchday 1, nữ) | Brazil 1–2 Norway (World Cup, Round of 16, nam) |
|---|---|---|
| A1 | Hello and welcome to Stamford Bridge in London for this Women's Super League matchday one clash between Chelsea and Manchester City. | Hello and welcome to New York/New Jersey Stadium in New Jersey for this FIFA World Cup Round of 16 tie between Brazil and Norway. |
| A2 | It's Sonia Bompastor's Chelsea against Andrée Alexander Jeglertz's Manchester City. | It's Carlo Ancelotti's Brazil against Ståle Solbakken's Norway. |
| A3 | It's the opening day of the season, and both sides want to start with three points. | It's knockout football: the winner goes through to the quarter-finals. |
| C1 | That's half-time. Chelsea lead 1-0. | The referee blows for half-time, and it's goalless: Brazil 0, Norway 0. |
| C2 | Stay with us, the second half is coming up. | Don't go anywhere, we'll be back for the second half. |
| G1 | That's full-time! Chelsea 2, Manchester City 1. | The final whistle goes: Norway win 2-1. |
| G3 | Chelsea take the three points on matchday one. | Norway are through to the quarter-finals; Brazil are out. |
| G4 | That's all from London. Thank you for watching, and goodbye. | Thanks for joining us from New York/New Jersey Stadium. Goodbye. |

---

## 7. Code (v5.0, file mới; code cũ giữ nguyên)

| File | Việc làm |
|---|---|
| `script_v2.py` | Biến ở mục 1, khuôn câu ở mục 2 (có điều kiện, chọn biến thể, bỏ khuôn thiếu biến), xếp lịch theo mục 3 |
| `no_flow_v2.py` | System prompt mục 4, tin nhắn mục 5, kiểm tra câu theo mục 3.7. LLM: Gemini |
| `tts_v2.py` | Đọc thành giọng (Gemini TTS), 2 giọng, ghép audio từng hiệp, lồng vào video |
| `gemini_client.py` | Gọi Gemini (REST); tự chuyển model khi model trước hết quota |

Chưa làm: hiệp phụ sau H1 và luân lưu (giai đoạn I), vì video chỉ có 2 hiệp chính.
