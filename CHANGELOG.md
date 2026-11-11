# Changelog

Mỗi lần sửa code thì tăng phiên bản. Notebook Colab được đặt tên theo phiên bản: `colab_run_vX.Y.ipynb`.
Code nằm trên GitHub: https://github.com/ThuLinh3009/soccer_project. Mỗi phiên bản là một commit.

## v4.6 (2026-11-11)
Test pipeline trên trận mới không có nhãn: video → luồng YES (model đã train) → khoảng trống → luồng NO (LLM ElevenLabs).
- `colab_test_pipeline_v4.6.ipynb` (mới): chạy trên Colab cho các trận trong `MyDrive/soccer_project/video_test/`.
  - Các bước: video 2 hiệp (`cut_halves.py`) → npy TimeSformer 768 chiều → phép ép đã học → npy 8576 chiều → `infer_match.py` (luồng YES) → `no_flow_llm.py --yes_events` (luồng NO) → timeline.
  - API key ElevenLabs đọc từ Colab Secrets (`ELEVENLABS_API_KEY`), không dán vào cell. Không có key thì chạy chế độ template.
  - npy 768 chiều và kết quả được lưu trên Drive (`video_test/features`, `video_test/output`).
- `infer_match.py` (mới): chạy luồng YES (spotting + dense captioning) trên **thư mục trận bất kỳ**, không cần nhãn và không cần nằm trong danh sách SoccerNet.
  - Dùng cùng checkpoint và cùng cách suy luận như `main.py` / `retune.py`: cửa sổ trượt 30 giây, NMS tham lam, mỗi sự kiện một câu GPT-2 từ clip 30 giây quanh nó.
  - Ghi `results_spotting.json` và `results_dense_captioning.json` cùng định dạng với `main.py`.
  - Lý do: `main.py` / `retune.py` chỉ chạy trên các trận có trong split SoccerNet và luôn chấm điểm bằng nhãn.
  - Đã kiểm thử trên CPU với model ngẫu nhiên và feature giả: NMS, clip và JSON đúng định dạng, `no_flow_llm.py --yes_events` đọc được.
- `feature_mapper.py apply`: thêm `--games` để áp phép ép cho các thư mục trận cho trước (trận mới), thay vì lấy theo split SoccerNet.
- `no_flow_llm.py`: thêm `--agent_cache`, nơi lưu id agent ElevenLabs. Notebook lưu trên Drive để không tạo agent mới mỗi phiên Colab.
- Các notebook khác: chỉ đổi số phiên bản thành v4.6.

## v4.5 (2026-11-11)
- `no_flow_llm.py`: chạy thật với LLM ElevenLabs (agent text-only, `gemini-2.5-flash`) trên 2 trận test, sửa các lỗi phát hiện ra.
  - Sửa lỗi câu trả lời bị lệch một lượt: agent gửi câu trả lời 2 lần (từng mảnh `agent_chat_response_part` và cả câu `agent_response`). Bản cũ lấy bản ghép từ các mảnh, nên câu `agent_response` còn sót lại bị đọc thành câu trả lời của lượt sau, và mỗi câu xuất hiện 2 lần. Nay chỉ lấy `agent_response`; các mảnh chỉ dùng dự phòng khi không nhận được câu hoàn chỉnh.
  - Prompt: cấm thêm chi tiết hay nhận xét không có trong fact ("young", "strong", "crucial"...). Danh sách dài như đội hình hay ghế dự bị chỉ nói phần chính, tối đa 35 từ.
  - Xoá các cụm chỉ thời gian trong ngày ("this afternoon", "tonight") vì LLM không biết giờ thi đấu. Câu dài quá 45 từ thì dùng lại câu fact gốc.
  - Sửa cảnh báo DeprecationWarning của `websockets`.
  - Kết quả với sự kiện FIFA làm mốc tạm:
    - Brazil 1-2 Norway: 51 câu nền.
    - Chelsea 2-1 Man City: 54 câu nền.
    - Không câu nào phải dùng lại câu fact gốc. Phút và tỉ số đều khớp metadata.
- Các notebook: chỉ đổi số phiên bản thành v4.5.

## v4.4 (2026-11-11)
- `no_flow_llm.py` (mới): luồng NO lúc test. LLM của ElevenLabs Agents (chế độ chat chỉ văn bản) sinh câu bình luận nền trong các khoảng trống giữa sự kiện. Không train, không cần nhãn.
  - Đầu vào: thư mục metadata của `fifa_crawl.py` (`facts.csv`, `events.csv`, `match_info.csv`), thư mục video hiệp (`--video_dir`, dùng để lấy độ dài mỗi hiệp) và sự kiện của luồng YES.
  - Sự kiện luồng YES: `--yes_events` (file `results_dense_captioning.json` hoặc `commentary_timeline.json` của model đã train). Khi model YES chưa xong thì tạm dùng `--events_from_fifa`, lấy sự kiện trong `events.csv` làm mốc khoảng trống.
  - Chọn fact cho từng chỗ trống bằng đúng luật của `commentary_timeline.py` (độ ưu tiên, thời điểm fact có hiệu lực, nhắc lại tỉ số...). Sau đó LLM viết lại thành 1 câu nói tự nhiên. Ngữ cảnh gửi cho LLM gồm phút, tỉ số lúc đó, sự kiện gần nhất và vài câu đã nói, để tránh lặp.
  - Chặn LLM bịa số: câu trả lời có con số không có trong ngữ cảnh, hoặc câu quá dài, thì dùng lại câu fact gốc.
  - Agent được tạo 1 lần qua API, id lưu ở `metadata/elevenlabs_agent.json`. Mỗi lần chạy, prompt và model của agent được cập nhật lại. API key lấy từ biến môi trường `ELEVENLABS_API_KEY`, không ghi ra file.
  - `--llm template` chạy offline, không gọi LLM, dùng câu fact gốc.
  - Đầu ra: `commentary_timeline.json` / `.txt` gồm [EVENT]/[FIFA] cho sự kiện và [INFO] cho câu luồng NO.
  - Đã chạy thử offline trên 2 trận test:
    - Brazil 1-2 Norway (World Cup 2026): 45 sự kiện, 51 câu nền.
    - Chelsea 2-1 Man City (WSL 2025/26): 36 sự kiện, 54 câu nền.
  - Đã kiểm thử phần WebSocket với server giả: ping/pong, nhận câu trả lời, tự kết nối lại khi bị ngắt.
- `commentary_timeline.py`: tách phần xếp lịch câu nền thành hàm `schedule_background()` và tách các tham số thành `add_slot_args()`, để dùng chung với `no_flow_llm.py`. Kết quả không đổi.
- Thêm thư viện `websockets`.
- Các notebook: chỉ đổi số phiên bản thành v4.4.

## v4.3 (2026-11-11)
- `cut_halves.py` (mới): cắt video full trận thành `1_224p.mp4` và `2_224p.mp4` theo cấu trúc SoccerNet.
  - Đầu vào: file video, `--t1` / `--t2` là giây giao bóng hiệp 1 / hiệp 2 trong video (dạng giây, `mm:ss` hoặc `hh:mm:ss`), `--out_dir`.
  - Mỗi hiệp bắt đầu đúng tại khung hình giao bóng, nên sự kiện trong `events.csv` của `fifa_crawl.py` (cột `half` và `second`) khớp với video.
  - Encode lại thay vì `-c copy`, vì `-c copy` chỉ cắt được ở keyframe.
  - Thu về 224p, bỏ tiếng, mặc định lấy 50 phút mỗi hiệp. Hiệp 1 không vượt quá điểm giao bóng hiệp 2.
  - Chỉ cần PyAV, không cần cài ffmpeg.
  - Đã kiểm thử trên video giả có đánh số từng khung hình: khung đầu tiên của mỗi hiệp đúng là khung tại `t1` / `t2`, kể cả khi `t2` lẻ (70,4 giây).
- Các notebook: chỉ đổi số phiên bản thành v4.3.

## v4.2 (2026-11-11)
- `fifa_crawl.py`: sửa lỗi tìm nhầm đội khi FIFA có nhiều đội cùng tên và ngang hạng.
  - Ví dụ: FIFA có 2 id "England" đội tuyển nam là 1888255 và 43942, nhưng chỉ id 43942 có trận.
  - `find_team` nay trả về mọi ứng viên ngang hạng. Crawler giữ ứng viên thật sự có trận với đội kia.
  - Đã chạy thử:
    - Mexico 2-3 England, vòng 16 đội World Cup 2026: 52 cầu thủ, 103 sự kiện, 61 câu fact.
    - Arsenal – Liverpool 2023/24: vẫn ra đúng 3 trận như trước.
- Các notebook: chỉ đổi số phiên bản thành v4.2.

## v4.1 (2026-11-11)
Mục tiêu: model bình luận sinh câu đa dạng hơn, không lặp một câu. Vẫn giữ npy 8576 chiều.
- `feature_mapper.py`: viết lại phần train phép ép **MLP** (`--mlp`) để chạy được với 40+ trận.
  - Bản cũ nạp toàn bộ dữ liệu vào RAM cùng lúc (hơn 10 GB với 40 trận).
  - Bản mới chỉ giữ npy 768 chiều (fp32) và npy Baidu (fp16) trên GPU, ghép các giây context của từng batch khi train.
  - Đã kiểm thử trên dữ liệu giả: train chạy được, và mapper lưu ra rồi nạp lại cho kết quả giống hệt.
- `colab_video2caption_v4.1.ipynb`:
  - Cell 2 có thêm cấu hình:
    - `MAPPER_MLP = True`: thử phép ép MLP, giữ nếu tốt hơn ridge trên valid.
    - `MAPPER_CONTEXT = 4`: dùng 9 giây TimeSformer quanh giây t, thay vì 5.
    - `RETUNE_NMS`, `MIN_UNIQUE_RATIO`.
    - Mặc định mới: `MODEL_NAME = "gpt2-video60-mlp"`, `MAX_EPOCHS = 20`.
  - Cell 3: mỗi cấu hình phép ép có file riêng, ví dụ `mapper_timesformer_mlp_c4.pt`. Đổi cấu hình thì tự học lại, không ghi đè phép ép cũ.
  - Cell 12:
    - Chỉ chọn trong các tổ hợp có số câu khác nhau ≥ 10% số sự kiện, rồi mới so METEOR. Trước đây chọn tổ hợp chỉ sinh 3 câu cho 1633 sự kiện.
    - Thử NMS 0.3 và 0.5, thay cho 4 mức.
    - In bảng retune đầy đủ.
  - `run()` bỏ các dòng thanh tiến trình để log gọn.
- `colab_video2npy_v4.1.ipynb`, `colab_run_v4.1.ipynb`, `kaggle_run_v4.1.ipynb`: chỉ đổi số phiên bản.

## v4.0 (2026-11-10)
- `commentary_timeline.py`: thêm tùy chọn `--events_only`. Timeline chỉ gồm các câu bình luận sự kiện (luồng YES), không chèn câu thông tin ngoài lề (luồng NO), không đọc metadata và không crawl.
- `colab_video2caption_v4.0.ipynb`:
  - Cell 13 thành **Timeline sự kiện (luồng YES)** và chạy với `--events_only`. Notebook train chỉ dành cho luồng YES. Luồng NO (metadata → LLM) thuộc bước test pipeline.
  - Sửa ghi chú cell 11: số trận lấy theo cell 5 (ví dụ 60 trận: 40 / 10 / 10), không còn ghi cứng "train 6, valid 2, test 2".
- `colab_video2npy_v4.0.ipynb`, `colab_run_v4.0.ipynb`, `kaggle_run_v4.0.ipynb`: chỉ đổi số phiên bản.

## v3.9 (2026-11-09)
- `fifa_crawl.py` (mới): crawl metadata trận đấu từ FIFA (API JSON công khai mà www.fifa.com dùng) ra CSV cho luồng NO / INFO.
  - **Đầu vào** (tham số dòng lệnh, hoặc nhập từ bàn phím nếu bỏ trống):
    - `--season`: ví dụ `2023` hoặc `2023/2024`.
    - `--team_a`, `--team_b`: câu lạc bộ hoặc đội tuyển.
    - Tùy chọn: `--competition`, `--match`, `--women`, `--form`, `--h2h_years`, `--out`.
  - **Đầu ra:** mỗi trận một thư mục trong `metadata/fifa/`, gồm:
    - `match_info.csv`, `lineups.csv`, `staff.csv`, `events.csv`
    - `standings_before.csv`: tính từ các trận **trước** giờ bóng lăn
    - `form.csv`, `head_to_head.csv`
    - `facts.csv`: câu bình luận có sẵn, kèm `priority`, `live`, `valid_from` / `valid_until` (hiệp, giây), `repeat_every`, cùng dạng `Fact` của `match_facts.py`
    - `raw/*.json`
  - Bàn thắng được nhận theo thời điểm tỉ số thay đổi: có cả bàn phạt đền và phản lưới, không tính loạt luân lưu. Thẻ phạt và thay người chỉ được nói từ phút xảy ra.
  - Phạm vi dữ liệu do FIFA quyết định, ví dụ Premier League chỉ có từ mùa 2020/2021. Các trận SoccerNet 2014–2017 không có.
  - Đã chạy thử: Arsenal – Liverpool mùa 2023/2024 (3 trận) và chung kết World Cup 2022 Argentina – France.
- Các notebook: chỉ đổi số phiên bản thành v3.9.

## v3.8 (2026-11-09)
- `colab_video2caption_v3.8.ipynb`: đọc được video **mp4** và các định dạng khác, không chỉ `*_224p.mkv`.
  - Nhận các file tên bắt đầu bằng số hiệp `1` hoặc `2`, đuôi `.mkv`, `.mp4`, `.avi`, `.mov` hoặc `.webm`. Ví dụ: `1_224p.mkv`, `2_720p.mp4`, `1.mp4`.
  - Một hiệp có nhiều độ phân giải thì ưu tiên 224p, vì trích nhanh nhất.
  - Video được gom về `/content/videos_all/<giải>/<mùa>/<trận>/{1,2}_video` (symlink), rồi trích bằng `--video_name "{half}_video"`.
  - Cảnh báo các trận chỉ có 1 hiệp.
- `colab_video2npy_v3.8.ipynb`, `colab_run_v3.8.ipynb`, `kaggle_run_v3.8.ipynb`: chỉ đổi số phiên bản.

## v3.7 (2026-11-09)
- `colab_video2caption_v3.7.ipynb`: luồng **từ đầu** (video của mình → npy → train model bình luận) chạy được khi **thêm nhiều video**.
  - Video lấy từ `soccer_project/dataset/`: **mọi file `.zip`** (bất kỳ tên) và/hoặc thư mục đã giải nén `<giải>/<mùa>/<trận>/{1,2}_224p.mkv`. Chỉ giải nén video chưa có. Tất cả được gom về `/content/videos_all` bằng symlink.
  - Cell 5 in số trận có video theo split, và báo lỗi nếu split train, valid hoặc test không có trận nào.
  - Cell 12 (mới): thử NMS 0,3 / 0,4 / 0,5 / 0,7 × top_k 1 / 3 trên **valid** bằng `retune.py`, tự lấy tổ hợp `METEOR_loose` cao nhất rồi chấm trên **test**. Không train lại. top_k 3 giảm việc lặp một câu.
  - Ghi chú: với 10 trận (train 6), model bình luận bị sập về một câu. Nên có tối thiểu khoảng 30 trận.
- `colab_video2npy_v3.7.ipynb`, `colab_run_v3.7.ipynb`, `kaggle_run_v3.7.ipynb`: chỉ đổi số phiên bản.

## v3.6 (2026-11-09)
- `colab_video2caption_v3.6.ipynb` (mới): nối **video → npy 8576 chiều** với **train model bình luận**, 13 cell chạy lần lượt.
  - Cell 6: video → npy TimeSformer 768 chiều. Dùng lại các hiệp đã trích trên Drive (`timesformer768/`).
  - Cell 7: học phép ép 768 → 8576. Bỏ qua nếu `sn-models/mapper_timesformer.pt` đã có, trừ khi `RETRAIN_MAPPER = True`.
  - Cell 8: `feature_mapper.py apply` cho cả train, valid và test, ra `1_/2_baidu_from_timesformer.npy`.
  - Cell 11: `main.py --features baidu_from_timesformer.npy` (classifying → captioning → spotting → dvc). Model bình luận chỉ thấy feature tạo từ video, không dùng npy Baidu gốc. Lưu ở `sn-models/gpt2-video10`, không ghi đè `gpt2-30games`.
  - `FEATURES = "timesformer768.npy"` để train thẳng trên npy 768 chiều, không qua phép ép (code tự nhận số chiều).
  - `SN_LOCAL_SUBSET=1` và `SN_FEATURES=FEATURES`: chỉ dùng các trận có video (train 6, valid 2, test 2).
  - Cell nào lỗi thì dừng tại cell đó (hàm `run()`).
- `colab_video2npy_v3.6.ipynb`, `colab_run_v3.6.ipynb`, `kaggle_run_v3.6.ipynb`: chỉ đổi số phiên bản.

## v3.5 (2026-11-06)
- `colab_video2npy_v3.5.ipynb`: **cell nào lỗi thì dừng ngay tại cell đó** và hiện log lỗi thật. Trước đây cell 6 và cell 7 chạy bằng `!python`, nên khi script lỗi notebook vẫn chạy tiếp, và lỗi chỉ lộ ra ở cell 8 dưới dạng `FileNotFoundError: mapper_timesformer_report.json`.
  - Cell 6: chạy `timesformer_extract.py` qua `run()`, in log trực tiếp, báo lỗi khi exit code ≠ 0. Vẫn lưu các hiệp đã xong lên Drive dù bị lỗi giữa chừng. Kiểm tra đủ npy 768 chiều cho mọi hiệp, nếu thiếu thì liệt kê hiệp còn thiếu.
  - Cell 7: in bảng ✅/❌ (TimeSformer 1/2, Baidu 1/2) cho từng trận, rồi chạy `feature_mapper.py` qua `run()`.
  - Cell 8: nếu chưa có file report thì báo rõ là cell 7 chưa chạy xong.
- `colab_run_v3.5.ipynb`, `kaggle_run_v3.5.ipynb`: chỉ đổi số phiên bản.

## v3.4 (2026-11-06)
- `colab_video2npy_v3.4.ipynb` (mới): notebook Colab gọn, chỉ có 9 cell **chạy lần lượt từ trên xuống**:
  1. GPU
  2. Cấu hình (`DRIVE_ROOT`)
  3. Mount Drive, kiểm tra video zip và weights
  4. Lấy code và cài thư viện
  5. Giải nén video, tải npy Baidu gốc
  6. Video → npy TimeSformer 768 chiều, sao lưu lên Drive
  7. Ép 768 → 8576
  8. Bảng độ giống với npy Baidu gốc
  9. Xem thử npy vừa tạo

  Không còn các cell train / chấm caption xen giữa.
- `colab_run_v3.4.ipynb` (luồng caption đầy đủ, kèm mục 12) và `kaggle_run_v3.4.ipynb` chỉ đổi số phiên bản.

## v3.3 (2026-11-06)
- `kaggle_run_v3.3.ipynb` (mới): chạy phần video → npy TimeSformer 768 chiều → ép thành 8576 → đo độ giống với npy Baidu gốc trên **Kaggle**.
  - **Input:** video và weights `.pdparams` lấy từ Kaggle Dataset (`/kaggle/input`), dù dataset đã giải nén hay còn là file `.zip`. Bỏ qua các file rác `__MACOSX`.
  - **Dữ liệu tải về:** npy Baidu gốc và nhãn tải từ HuggingFace vào `/kaggle/tmp`.
  - **2 GPU T4 chạy song song:** các trận được chia cho 2 GPU, mỗi GPU một tiến trình. Notebook in tiến độ mỗi phút và lưu log riêng cho từng GPU.
  - **Kết quả:** lưu ở `/kaggle/working/outputs`, gồm npy TimeSformer, phép ép đã học và bảng độ giống. Khi thêm output của lần chạy trước làm Input, notebook dùng lại npy đã trích, không trích lại.
  - **Bảng độ giống:** hiển thị cho valid và test, kèm hai mốc so sánh.
- Notebook Colab đổi tên thành `colab_run_v3.3.ipynb`, nội dung không đổi.

## v3.2 (2026-11-06)
Mục 12 chạy độc lập: video → npy TimeSformer 768 chiều → ép thành 8576 → đo độ giống với npy Baidu gốc. Không cần train, không cần cell 5–11.
- Cell 12a tự cài `SoccerNet` và `av`. Trước đây `av` (đọc video) chưa được cài nếu bỏ qua cell 5.
- Bộ chuyển đổi và file `_report.json` (bảng độ giống) được lưu thẳng vào `sn-models` trên Drive.
- Ghi rõ thứ tự chạy (cell 1–4 rồi 12a–12d). 12e–12f (chấm caption bằng model cũ) đánh dấu là tùy chọn.

## v3.1 (2026-11-06)
Notebook chạy được trên tài khoản Google khác.
- Mọi đường dẫn Drive giờ tính từ một biến `DRIVE_ROOT` ở cell 2, mặc định `/content/drive/MyDrive/soccer_project`. Các đường dẫn đó gồm `sn-models`, `dataset/Dataset.zip`, weights `.pdparams` và `timesformer768`.
- Cell 3: nếu không thấy `DRIVE_ROOT`, tự tìm thư mục `soccer_project` trong `MyDrive` (kể cả lối tắt tới thư mục được chia sẻ) và trong `Shared drives`, rồi in nội dung thư mục tìm được.
- Cell 12a: báo lỗi rõ ràng nếu thiếu `Dataset.zip`.

## v3.0 (2026-11-06)
Cách B: dùng model đã train trên feature Baidu (8576 chiều) với feature trích từ **video**, không train lại model caption/spotting.
- `timesformer_extract.py` (mới): bản PyTorch của TimeSformer mà Baidu fine-tune trên SoccerNet (repo `baidu-research/Soccernet-features`, PaddlePaddle).
  - **Kiến trúc:** ViT-Base, attention chia không gian / thời gian, 16 khung 224×224.
  - **Luồng xử lý giống bản gốc:** lấy khung theo lưới 5 fps, mỗi giây một đoạn 5 giây, chia 255, resize cạnh ngắn về 224, cắt giữa. Feature là token CLS sau LayerNorm cuối, 768 chiều.
  - **Đã kiểm tra:** với cùng weights, kết quả trùng bản Paddle gốc (sai lệch tối đa 2e-6, cosine 1,0000). File `.pdparams` đọc được mà không cần cài Paddle.
  - **Khác bản gốc, có chủ đích:**
    - Mỗi giây video cho 1 dòng, đoạn 5 giây có tâm ở giây đó (`--center_offset 2`), nên file có cùng số dòng với npy Baidu.
    - Chạy batch trên GPU với fp16, thay vì batch 1, fp32 và 2–3 giờ mỗi hiệp như bản gốc.
  - **Video:** chạy được với video 224p của SoccerNet và mp4 bất kỳ. Video lớn được thu về cạnh ngắn 256 trước, như Baidu làm. Đọc 1 hiệp 224p mất khoảng 16 giây.
- `feature_mapper.py` (mới): học bộ chuyển đổi TimeSformer 768 → Baidu 8576 từ các trận có cả video lẫn npy Baidu.
  - `train`:
    - Tự tìm độ lệch thời gian giữa hai file.
    - Ridge regression trên 5 giây quanh giây t (`--context 2`). Có thể thêm MLP (`--mlp`), chỉ giữ nếu tốt hơn trên valid.
    - Báo cosine (tổng và theo 5 khối TPN/GTA/VTN/irCSN/I3D-Slow), tỉ lệ số giây đạt cosine ≥ 0,95, Pearson r và R². Kèm hai mốc so sánh: Baidu so với giây kế tiếp (khoảng 0,94) và hai giây ngẫu nhiên (khoảng 0,67).
  - `apply`: ghi `1_/2_baidu_from_timesformer.npy`. `--ref_name` tạo bản sao npy thật của cùng các trận để so sánh công bằng.
  - Đã thử với dữ liệu giả có độ lệch +2 giây: tìm đúng độ lệch.
- `utils.py`: biến môi trường `SN_FEATURES` chọn file feature dùng để liệt kê các trận khi chấm điểm. Mặc định vẫn là Baidu. `commentary_timeline.py` dùng chung biến này.
- Notebook mục 12:
  - Giải nén video từ `Dataset.zip` trên Drive, tải nhãn và npy của đúng các trận đó.
  - Trích TimeSformer, sao lưu lên Drive.
  - Train bộ chuyển đổi (train / valid / test theo split SoccerNet).
  - Chạy model cũ trên npy thật và npy giả của cùng các trận test, so METEOR / a_mAP.
  - Weights `.pdparams` phải tải bằng trình duyệt từ OneDrive, vì link chặn tải tự động, rồi đặt vào `MyDrive/soccer_project/weights/`.

## v2.2 (2026-11-04)
Đối chiếu dữ liệu crawl (football-data.co.uk) với SoccerNet trên toàn bộ 405 trận của 5 giải (bỏ 108 trận Champions League): **405/405 trận ghép được, 404/405 trùng tỉ số**. Trận lệch duy nhất là Real Madrid - Rayo ngày 20/12/2015: tên thư mục SoccerNet ghi "1 - 0", thực tế là 10-2. Trên 9 trận có nhãn trên máy: trọng tài trùng 9/9.
- `match_facts.py`: `lineup.facts` của SoccerNet **thiếu bàn thắng từ phạt đền**: Cazorla trong trận Crystal Palace 1-2 Arsenal, và một bàn của Swansea trong trận Chelsea 2-2 Swansea. Nếu số bàn trong `facts` không khớp tỉ số chung cuộc, timeline không đọc tỉ số đang diễn ra nữa, chỉ báo cầu thủ ghi bàn. Tỉ số hiệp 1 khi đó lấy từ CSV (`HTHG`/`HTAG`).
- `football_data.py`: thêm alias `Internazionale` → Inter, `1. FSV Mainz 05` → Mainz, `Borussia` → M'gladbach. Đọc thêm tỉ số hiệp 1. `find_match()` tìm trận theo mùa và hai đội, vì mỗi cặp đội nhà - đội khách chỉ gặp nhau 1 lần mỗi mùa.
- Một số trận challenge có ngày sai trong tên thư mục SoccerNet (Empoli - Inter, Juventus - Inter). Bảng xếp hạng, phong độ và đối đầu giờ tính theo ngày trong lịch thi đấu thật.

## v2.1 (2026-11-03)
- `retune.py` (mới): chạy lại spotting và DVC từ checkpoint đã train, không train lại. Thử nhiều `NMS_threshold` × `top_k` trên một split, in METEOR, CIDEr, a_mAP, số lần báo sự kiện và số câu khác nhau, lưu `retune_<split>.csv`, và để lại `outputs/<split>` của tổ hợp tốt nhất.
- Timeline, luồng NO:
  - Bàn thắng, thẻ phạt và thay người được nói **ngay khi biết** (`live`), không chờ khung 60 giây. Đo trên trận Man Utd - Arsenal: trễ còn +2 đến +30 giây (trước đây +24 đến +172 giây).
  - Gộp các lần thay người trong cùng một phút thành một câu.
  - Chuyện ngoài lề nhỏ (quốc tịch, dự bị, số bàn mùa giải) chỉ nói khi khoảng im lặng ≥ `--long_gap` (120 giây), và không nói trong `--goal_cooldown` (120 giây) sau bàn thắng.
  - Cầu thủ đã bị thay ra thì không được giới thiệu nữa.
  - `--spacing` mặc định tăng từ 60 lên 90 giây. Thêm `--min_info_gap`, `--long_gap`, `--low_priority`, `--goal_cooldown`.
- Notebook: bước 10 chạy retune (10a trên valid, 10b áp dụng lên test), bước 11 tạo timeline.

## v2.0 (2026-11-03)
Bình luận theo 2 luồng: YES khi có sự kiện, NO khi không có sự kiện.
- `commentary_timeline.py` (mới): ghép lời bình sự kiện của model (`results_dense_captioning.json`, luồng YES) với bình luận ngoài lề ở các khoảng im lặng từ 45 giây trở lên (luồng NO), rồi ghi ra `commentary_timeline.json/.txt` cho từng trận. Dùng `--events_from_labels` để thử với lời bình thật, không cần model.
- `match_facts.py` (mới): tạo các mẩu thông tin có mốc thời gian, mỗi mẩu chỉ được nói sau khi đã xảy ra:
  - metadata SoccerNet: giới thiệu trận, trọng tài, khán giả, HLV, sơ đồ, đội hình, đội trưởng, dự bị, quốc tịch cầu thủ;
  - diễn biến tới thời điểm hiện tại (từ `lineup.facts`): tỉ số (nhắc lại mỗi 10 phút), tỉ số hiệp 1, thẻ phạt, thay người. Không dùng trường `score` (tỉ số chung cuộc).
- `football_data.py` (mới): tải và cache CSV của football-data.co.uk cho 5 giải VĐQG. Tính bảng xếp hạng, phong độ 5 trận và lịch sử đối đầu tính đến **trước ngày thi đấu**. Ghép tên đội SoccerNet sang football-data, đã kiểm tra khớp cả 19 đội của 30 trận.
- Notebook: thêm bước 10 tạo và xem timeline.
- `.gitignore`: bỏ qua `metadata/` (cache CSV) và `timelines/`.

## v1.9 (2026-11-03)
- `download_subset.py`: thêm `--list_only` để in danh sách trận sẽ dùng (split, giải, mùa, ngày giờ, tỉ số) mà không tải.
- Notebook: cell 6a xem danh sách trận trước, cell 6b mới tải dữ liệu.

## v1.8 (2026-11-03)
- Giảm RAM: feature được mở bằng `np.load(mmap_mode="r")` (hàm `load_feats` trong `dataset.py`) thay vì đọc cả trận vào RAM. Mỗi mẫu chỉ đọc đúng 30 dòng cần dùng.
- `SoccerNetVideoProcessor`: bỏ bản sao `np.pad(..., "edge")` của từng hiệp, thay bằng giới hạn chỉ số. Áp dụng cho `SoccerNetCaptions`, `SoccerNetClassification` và `PredictionCaptions`.
- `SoccerNetClips`: chỉ lưu vị trí bắt đầu của mỗi đoạn, không còn tạo sẵn và `np.concatenate` mọi đoạn.
- Đã kiểm tra trên 9 trận: mọi mẫu giống hệt bản v1.7. RAM khi tạo dataset giảm từ 1,07 GB xuống 0,03 GB (caption, 5 trận train), và từ 0,97 GB xuống ~0 (spotting, 5 trận train).
- Notebook: mặc định 30 trận (20/5/5), `MAX_EPOCHS = 10`, `EVAL_FREQ = 5`, `MODEL_NAME = "gpt2-30games"`.

## v1.7 (2026-11-03)
- Sửa lỗi hết RAM ở bước test spotting (`DataLoader worker ... is killed by signal: Killed`). `SoccerNetClipsTesting` trước đây cắt sẵn cả hiệp thành các đoạn 30 giây, tốn khoảng 2,8 GB RAM mỗi hiệp. Giờ dataset chỉ trả về feature gốc (khoảng 93 MB), và `test_spotting` dùng `LazyClips` (`dataset.py`) để cắt từng nhóm 256 đoạn trên GPU. Đã kiểm tra: kết quả giống hệt `feats2clip`.

## v1.6 (2026-11-03)
- Notebook: tách bước mount Drive thành cell riêng (cell 3), có `force_remount=True`. Nếu `mount failed` thì vẫn chạy tiếp và lưu `models/` trên ổ Colab.
- Notebook: thêm cell nén và tải kết quả về máy khi không dùng Drive.
- Notebook: đánh số lại các cell: lấy code là cell 4, train là cell 8.

## v1.5 (2026-11-03)
- Notebook: clone code từ repo `https://github.com/ThuLinh3009/soccer_project`.

## v1.4 (2026-11-03)
- Notebook: lấy code bằng `git clone` từ GitHub thay vì giải nén file zip trên Drive. Chạy lại cell 3 để `git pull` bản mới, dữ liệu đã tải vẫn giữ nguyên.
- `.gitignore`: bỏ qua `dataset/`, `videos/`, `.venv/` và `download.log`.

## v1.3 (2026-11-03)
- Notebook: đặt `JAVA_TOOL_OPTIONS="-XX:-UseContainerSupport -Xlog:disable"` để Java trên Colab không in cảnh báo `Cgroup` vào stdout. Cảnh báo này làm METEOR lỗi `ValueError: could not convert string to float`.
- Notebook: thêm cell kiểm tra METEOR ngay sau bước cài thư viện.
- Notebook: thêm `NUM_WORKERS = 2` (truyền vào `--max_num_worker`) vì Colab chỉ có 2 CPU.
- Notebook: đổi tên thành `colab_run_v1.3.ipynb` và ghi số phiên bản ở đầu notebook.
- Notebook: tự chọn file zip `soccernet-caption-deltalab*.zip` mới nhất trong `MyDrive/soccer_project/`, nên file zip có thể đặt tên theo phiên bản.

## v1.2 (2026-11-03)
- Notebook: đọc code từ file zip `MyDrive/soccer_project/soccernet-caption-deltalab.zip` và lưu model vào `MyDrive/soccer_project/sn-models`.
- `train.py`: tắt chỉ số SPICE, vì code không dùng và nó cần Stanford CoreNLP.
- `train.py`: khi bật `SN_LOCAL_SUBSET=1`, hàm chấm điểm DVC của SoccerNet chỉ đọc các trận đã tải.

## v1.1 (2026-11-03)
- Thêm `download_subset.py` để tải N trận mỗi split từ HuggingFace.
- `dataset.py`: chỉ import `torchtext` khi dùng `--model_type lstm`.
- Thêm notebook Colab đầu tiên.

## v1.0 (2026-11-03)
- `utils.py`: thêm `get_list_games()`. Khi bật `SN_LOCAL_SUBSET=1`, hàm chỉ trả về các trận đã có trên máy.
- `dataset.py`: dùng `get_list_games()` và bỏ qua bước tự tải dataset khi bật `SN_LOCAL_SUBSET=1`.
