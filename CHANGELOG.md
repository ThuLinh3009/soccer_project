# Changelog

Mỗi lần sửa code thì tăng phiên bản. Notebook Colab được đặt tên theo phiên bản: `colab_run_vX.Y.ipynb`.
Code nằm trên GitHub: https://github.com/ThuLinh3009/soccer_project. Mỗi phiên bản là một commit.

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
