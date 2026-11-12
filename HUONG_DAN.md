# Hướng dẫn cài đặt và chạy dự án: AI bình luận bóng đá tự động

Hệ thống nhận **video một trận đấu** và tạo **timeline bình luận** theo thời gian, gồm hai luồng:

| Luồng | Làm gì | Có train không |
|---|---|---|
| **YES** | Bắt sự kiện trong video (phạt góc, sút, thẻ...) và sinh câu bình luận cho từng sự kiện | **Có**: train trên dữ liệu SoccerNet |
| **NO** | Trong các khoảng trống không có sự kiện, LLM của ElevenLabs nói thông tin ngoài lề (đội hình, phong độ, tỉ số...) lấy từ metadata FIFA | **Không**: chỉ chạy lúc test, không có nhãn |

```
video trận đấu ─► cắt 2 hiệp ─► TimeSformer (768 chiều/giây) ─► phép ép ─► npy 8576 chiều
                                                                                │
                                         luồng YES: model đã train ◄────────────┘
                                         (bắt sự kiện + GPT-2 sinh câu)
                                                    │ khoảng trống giữa các sự kiện
metadata FIFA (fifa_crawl.py) ─► facts.csv ─► luồng NO: LLM ElevenLabs viết câu nền
                                                    │
                                         timeline YES + NO (json / txt)
```

Code gốc của phần bình luận là của [DeLTA Lab](https://github.com/gladuz/soccernet-caption-deltalab) (QFormer + GPT-2, SoccerNet 2024). Weight TimeSformer là của Baidu. Dự án này thêm: trích feature từ video, phép ép 768 → 8576, chạy trên trận mới, luồng NO, cắt video, crawl FIFA.

---

## 1. Cần chuẩn bị

| Thứ cần có | Dùng cho | Ghi chú |
|---|---|---|
| Tài khoản Google, **Google Colab** (GPU T4 hoặc A100) và **Google Drive** | Train và chạy test pipeline | Colab Pro nếu train nhiều trận |
| **Video SoccerNet** (`1_224p.mkv`, `2_224p.mkv` mỗi trận) | Train luồng YES | Thuộc NDA của SoccerNet: chỉ để trên Drive **Private** |
| **Weight TimeSformer** `*.pdparams` | Video → feature 768 chiều | Tải bằng trình duyệt từ link OneDrive trong README của [baidu-research/Soccernet-features](https://github.com/baidu-research/Soccernet-features) |
| **Tài khoản ElevenLabs** + API key | LLM cho luồng NO | Key có quyền **ElevenAgents (Write)** |
| Máy tính Windows/Linux có **Python 3.10+** | Cắt video, crawl metadata FIFA | Không cần GPU |
| Video trận cần test (full trận) | Test pipeline | Phải có quyền sử dụng hợp lệ |

---

## 2. Cài đặt trên máy local (chuẩn bị trận test)

```powershell
git clone https://github.com/ThuLinh3009/soccer_project.git soccernet-caption-deltalab
cd soccernet-caption-deltalab
python -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install av numpy tqdm SoccerNet websockets
```

| Thư viện | Dùng cho |
|---|---|
| `av` (PyAV) | `cut_halves.py`: cắt video, **không cần cài ffmpeg** |
| `numpy`, `tqdm`, `SoccerNet` | `no_flow_llm.py`, `commentary_timeline.py` |
| `websockets` | Gọi LLM ElevenLabs |

`fifa_crawl.py` chỉ dùng thư viện chuẩn của Python.

Trên Colab, các notebook tự `git clone` code và cài thư viện, không cần cài gì thêm.

---

## 3. Cấu trúc thư mục trên Google Drive

```
MyDrive/soccer_project/
├── dataset/                 video SoccerNet để train: file .zip hoặc thư mục <giải>/<mùa>/<trận>/1_224p.mkv
├── weights/*.pdparams       weight TimeSformer của Baidu
├── timesformer768/          (tự tạo) npy 768 chiều của các trận train, dùng lại giữa các phiên
├── sn-models/               (tự tạo) model đã train + phép ép + id agent ElevenLabs
│   ├── gpt2-video60-mlp/        spotting/, caption/, classifying/, outputs/, retune_*.csv
│   ├── mapper_timesformer_mlp_c4.pt
│   └── elevenlabs_agent.json
└── video_test/              trận mới để test
    ├── <giải>/<mùa>/<trận>/1_224p.mp4, 2_224p.mp4
    ├── metadata/<trận>/         facts.csv, events.csv, lineups.csv, match_info.csv...
    ├── features/                (tự tạo) npy 768 chiều của trận test
    └── output/                  (tự tạo) yes/<trận>/..., timeline/<trận>/...
```

Thư mục `<trận>` trong `video_test/` và trong `video_test/metadata/` phải **cùng tên**, ví dụ `2026-07-05 - Brazil 1 - 2 Norway`.

---

## 4. Giai đoạn 1: Train luồng YES

Notebook: **`colab_video2caption_vX.Y.ipynb`** (mở trên Colab, chạy lần lượt cell 1 → 13).

| Cell | Việc làm |
|---|---|
| 1–4 | GPU, cấu hình, mount Drive, lấy code + cài thư viện |
| 5 | Giải nén video, tải nhãn SoccerNet + npy Baidu gốc của các trận có video |
| 6 | Video → npy TimeSformer 768 chiều (5–10 phút mỗi hiệp trên T4) |
| 7 | Học phép ép 768 → 8576 trên các trận train (ridge, và MLP nếu tốt hơn) |
| 8 | Tạo npy 8576 chiều cho mọi trận |
| 9 | Độ giống với npy Baidu gốc (cosine, R²) |
| 10–11 | Train model bình luận (`main.py`): classifying → captioning → spotting → dvc |
| 12 | Chọn ngưỡng NMS và `top_k` trên valid, chấm trên test |
| 13 | Timeline sự kiện của các trận test (chỉ luồng YES) |

**Cấu hình chính ở cell 2:**
- `MODEL_NAME`: tên thư mục model trong `sn-models/`. Đổi phép ép thì đặt tên mới.
- `MAPPER_MLP`, `MAPPER_CONTEXT`: cách học phép ép.
- `MAX_EPOCHS`, `BATCH_SIZE`, `RETUNE_NMS`, `MIN_UNIQUE_RATIO`.

**Cần bao nhiêu trận:** tối thiểu khoảng 30 trận, chia đủ train / valid / test theo danh sách chính thức của SoccerNet. Với 10 trận, model chỉ lặp lại một câu.

**Kết quả hiện tại** (60 trận, `gpt2-video60-mlp`):
- Phép ép: ridge, context 4, R² 0,57 trên valid.
- Cấu hình đã chốt (v4.14): **NMS 0.4**, top_k 3. Đổi NMS không cần train lại.
- Test (10 trận) với NMS 0.4: 1128 sự kiện, 588 câu khác nhau, Recall_loose 0,78, Precision_loose 0,75, a_mAP_loose 0,39, METEOR_loose 0,21.
- So sánh trên valid:

  | NMS | Recall_loose | Precision_loose | Sự kiện / trận |
  |---|---|---|---|
  | 0.3 | 0,86 | 0,71 | ~160 |
  | **0.4** | **0,76** | **0,75** | **~111** |
  | 0.5 | 0,61 | 0,76 | ~71 |
  | 0.6 | 0,42 | 0,82 | ~35 |
  | 0.7 | 0,21 | 0,80 | ~14 |

---

## 5. Giai đoạn 2: Chuẩn bị trận test (máy local)

### 5.1. Cắt video thành 2 hiệp
1. Tìm thời điểm giao bóng trong video gốc:
   - `t1` = giao bóng hiệp 1, `t2` = giao bóng hiệp 2.
   - Cách nhanh: đọc đồng hồ trên bảng tỉ số. Ví dụ phút 11:00 của video hiện đồng hồ 09:33 thì `t1` = 1:27.
2. Chạy:
```powershell
python cut_halves.py "match.mp4" --t1 1:27 --t2 53:15 --duration 3540 `
    --out_dir "..\video_test\fifa_world-cup\2026\2026-07-05 - Brazil 1 - 2 Norway"
```
- Ra `1_224p.mp4` và `2_224p.mp4`: cắt chính xác từng khung hình, cao 224 pixel, không có tiếng.
- `--duration`: số giây giữ lại mỗi hiệp, mặc định 3000. Nếu bù giờ dài thì tăng lên, ví dụ 3540.
- Hiệp nào ngắn hơn 44 phút thì script in `WARNING`: kiểm tra lại `t1` / `t2`.

### 5.2. Crawl metadata FIFA
```powershell
python fifa_crawl.py --season 2026 --team_a Brazil --team_b Norway --competition "World Cup" --out ..\video_test\metadata
python fifa_crawl.py --season 2025 --team_a Chelsea --team_b "Manchester City" --women --match 1 --out ..\video_test\metadata
```
- `--women` cho đội nữ. `--match N` chọn trận thứ N nếu có nhiều trận.
- Mỗi trận ra một thư mục gồm: `match_info.csv`, `lineups.csv`, `staff.csv`, `events.csv`, `form.csv`, `head_to_head.csv`, `standings_before.csv`, **`facts.csv`** (câu fact cho luồng NO) và `raw/` (JSON gốc của FIFA).
- Đổi tên thư mục metadata cho trùng với tên thư mục video của trận.

### 5.3. Upload lên Drive
Upload `<giải>/...` (2 file hiệp) và `metadata/<trận>/` vào `MyDrive/soccer_project/video_test/`. Để **Private**.

---

## 6. Giai đoạn 3: Test pipeline trên trận mới

Notebook: **`colab_test_pipeline_vX.Y.ipynb`**.

**Trước khi chạy:** trên Colab, mở biểu tượng 🔑 (Secrets):
- **Thêm giá trị bí mật mới**, tên `ELEVENLABS_API_KEY`, dán API key ElevenLabs.
- Bật công tắc **Quyền truy cập vào sổ tay**.
- Không dán key vào cell hay vào file.

| Cell | Việc làm | Ghi chú |
|---|---|---|
| 1–4 | GPU, cấu hình, mount Drive, lấy code | Cell 3 in ✅ cho từng trận có đủ 2 hiệp + metadata |
| 5 | Video → npy 768 chiều | Lưu ở `video_test/features/`, chạy lại không trích lại |
| 6 | Phép ép → npy 8576 chiều | Dùng đúng phép ép đã học ở giai đoạn 1 |
| 7 | **Luồng YES** (`infer_match.py`) | Ra `output/yes/<trận>/results_dense_captioning.json` |
| 8 | **Luồng NO** (`no_flow_llm.py`) | Kiểm tra key trước, rồi gọi LLM cho các trận trong `NO_FLOW_GAMES` |
| 9 | Xem timeline | `[EVENT]` = YES, `[INFO ]` = NO |

**Cấu hình chính ở cell 2:**
- `MODEL_NAME`, `MAPPER_FILE`: cặp model + phép ép đã train (phải đi cùng nhau).
- `NMS_THRESHOLD`, `TOP_K`: lấy từ cell 12 của notebook train. Muốn bắt nhiều sự kiện hơn thì hạ `NMS_THRESHOLD` xuống 0.3.
- `LLM`: `"elevenlabs"` gọi LLM, `"template"` không gọi LLM (dùng câu fact gốc).
- `LLM_MODEL`: LLM của agent, mặc định `gemini-2.5-flash`.
- `NO_FLOW_GAMES`: chỉ chạy luồng NO cho các trận này, để tiết kiệm credit. `[]` = mọi trận.

**Kết quả** (trên Drive, `video_test/output/`):
- `yes/<trận>/results_spotting.json`, `results_dense_captioning.json`
- `timeline/<trận>/commentary_timeline.json` và `.txt`. Mỗi câu NO có `"source": "llm"` hoặc `"template"`, và `"fact"` là câu gốc.

### Chạy luồng NO trên máy local (không cần GPU)
Khi đã có `results_dense_captioning.json` (tải từ Drive về):
```powershell
$env:ELEVENLABS_API_KEY = "<key>"      # chỉ tồn tại trong cửa sổ PowerShell này
python no_flow_llm.py --metadata "..\video_test\metadata\<trận>" --video_dir "..\video_test\<giải>\<mùa>\<trận>" `
    --yes_events "<đường dẫn>\results_dense_captioning.json" --out_dir ..\video_test\output_no_flow
```
Thêm `--llm template` để chạy thử không tốn credit.

---

## 7. Luồng NO hoạt động thế nào

1. **Tìm khoảng trống** giữa hai sự kiện YES liên tiếp:
   - chừa 15 giây sau sự kiện (`--after_event`) và 10 giây trước sự kiện tiếp theo (`--before_event`);
   - cứ 90 giây đặt một câu (`--spacing`);
   - bỏ khoảng ngắn hơn 45 giây (`--min_gap`).
2. **Chọn fact** trong `facts.csv` cho mỗi chỗ: fact đang có hiệu lực (ví dụ tỉ số sau bàn thắng), ưu tiên cao nhất, chưa nói. Bàn thắng, thẻ, thay người được nói ngay khi xảy ra.
3. **LLM viết lại** thành một câu nói. LLM nhận phút, tỉ số, fact, sự kiện gần nhất và vài câu đã nói. Prompt cấm bịa thông tin.
4. **Kiểm tra:** câu có con số không có trong ngữ cảnh, hoặc dài quá 45 từ, thì dùng câu fact gốc.

LLM chạy qua **ElevenLabs Agents** ở chế độ chỉ văn bản (WebSocket). Agent được tạo một lần, id lưu ở `elevenlabs_agent.json`.

---

## 8. Các file chính

| File | Vai trò |
|---|---|
| `main.py`, `classifying.py`, `captioning.py`, `spotting.py`, `train.py`, `model*.py`, `dataset.py` | Code train/test gốc của DeLTA Lab (luồng YES) |
| `timesformer_extract.py` | Video → npy TimeSformer 768 chiều (bản PyTorch của model Baidu) |
| `feature_mapper.py` | Học (`train`) và áp (`apply`) phép ép 768 → 8576 |
| `retune.py` | Chọn ngưỡng NMS / `top_k` không cần train lại |
| `infer_match.py` | Luồng YES trên trận mới, không cần nhãn |
| `cut_halves.py` | Cắt video full trận thành 2 hiệp |
| `fifa_crawl.py` | Crawl metadata FIFA → CSV + `facts.csv` |
| `no_flow_llm.py` | Luồng NO với LLM ElevenLabs |
| `commentary_timeline.py`, `match_facts.py`, `football_data.py` | Xếp lịch câu nền; luồng NO cũ dùng câu mẫu từ metadata SoccerNet |
| `colab_video2caption_vX.Y.ipynb` | Notebook train (giai đoạn 1) |
| `colab_test_pipeline_vX.Y.ipynb` | Notebook test pipeline (giai đoạn 3) |
| `colab_video2npy`, `colab_run`, `kaggle_run` | Notebook phụ: chỉ trích feature / chạy trên npy Baidu / chạy trên Kaggle |
| `CHANGELOG.md` | Thay đổi của từng phiên bản |

---

## 9. Lỗi thường gặp

| Lỗi | Nguyên nhân và cách sửa |
|---|---|
| `HTTP 401 Invalid API key` | Key sai, đã xoá, hoặc dán thiếu. Tạo key mới, dán lại vào secret `ELEVENLABS_API_KEY`, bật quyền truy cập |
| `This request exceeds your quota limit` | Hết credit ElevenLabs hoặc chạm hạn mức của key. Xem trang Usage; giảm số trận bằng `NO_FLOW_GAMES` |
| `⚠️ không đọc được secret` | Chưa tạo secret hoặc chưa bật quyền truy cập cho notebook |
| Luồng YES bắt được ít sự kiện | Hạ `NMS_THRESHOLD` xuống 0.3 rồi chạy lại cell 7. Video mới khác dữ liệu train (năm, đồ hoạ, bóng đá nữ) nên model kém tự tin hơn |
| Câu YES có `[PLAYER]`, `[TEAM]` | Model được train trên câu đã ẩn tên; chưa có bước điền tên |
| Cell 3 báo thiếu hiệp hoặc metadata | Kiểm tra tên file `1_224p.mp4` / `2_224p.mp4` và tên thư mục metadata trùng tên thư mục trận |
| Excel hiện sai dấu trong CSV | Mở bằng Data → From Text/CSV, chọn UTF-8 |
| `cut_halves.py` báo WARNING | Hiệp ngắn hơn 44 phút: kiểm tra lại `t1`, `t2` và độ dài video |

---

## 10. Bảo mật và bản quyền

- Video SoccerNet thuộc NDA. Video trận test có bản quyền. Mọi thư mục video trên Drive / Kaggle / HuggingFace để **Private**.
- API key chỉ để trong Colab Secrets hoặc biến môi trường; không ghi vào file, không commit lên GitHub. Nếu key bị lộ thì xoá và tạo key mới.
- Chỉ dùng video có quyền sử dụng hợp lệ. Code không tải video từ YouTube hay nguồn có DRM.

## 11. Quy ước phiên bản

Mỗi lần sửa code: tăng phiên bản `vX.Y`, ghi vào `CHANGELOG.md`, đổi tên các notebook theo phiên bản mới, rồi commit và push. Trên Colab, chạy lại cell lấy code (cell 4) để cập nhật.
