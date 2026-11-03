# Changelog

Mỗi lần sửa code thì tăng phiên bản. Notebook Colab được đặt tên theo phiên bản: `colab_run_vX.Y.ipynb`.
Code nằm trên GitHub: https://github.com/ThuLinh3009/soccernet-caption-deltalab. Mỗi phiên bản là một commit.

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
