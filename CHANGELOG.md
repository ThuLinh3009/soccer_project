# Changelog

Mỗi lần sửa code thì tăng phiên bản. Notebook Colab được đặt tên theo phiên bản: `colab_run_vX.Y.ipynb`.
Code nằm trên GitHub: https://github.com/ThuLinh3009/soccer_project. Mỗi phiên bản là một commit.

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
