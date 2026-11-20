# SoccerNet 2024 - Dense Video Captioning

> **Hướng dẫn tiếng Việt cho dự án AI bình luận bóng đá (cài đặt, train, test pipeline YES/NO): xem [HUONG_DAN.md](docs/HUONG_DAN.md).**

## Cấu trúc thư mục (v7.0)
```
soccer_project/
├── deltalab/      model DeLTA Lab (QFormer + GPT-2), luồng YES: train (main.py), chỉnh NMS/top-k (retune.py),
│                  chạy trên một trận (infer_match.py); dataset, model, model_gpt, gpt, netvlad, loss, train, utils
├── features/      video → npy: cut_halves.py (cắt hiệp), timesformer_extract.py (768 chiều),
│                  feature_mapper.py (768 → 8576 kiểu Baidu), download_subset.py (tải SoccerNet)
├── crawler/       metadata trận đấu: fifa_crawl.py, crawl_web.py (website crawl), football_data.py, match_facts.py,
│                  prepare_metadata.py (FIFA + Wikipedia → video_test/metadata/<trận>, chỉ thông tin trước trận)
├── commentary/    luồng NO: script_v2.py (luật kịch bản), no_flow_v2.py (LLM viết câu), no_flow_llm.py (bản v1),
│                  commentary_timeline.py (xếp câu lên timeline)
├── voice/         đọc thành tiếng: tts_v2.py (OpenAI / Gemini / Kokoro), voice_samples.py (nghe thử giọng)
├── api/           gọi API bên ngoài: openai_client.py, gemini_client.py (key chỉ lấy từ biến môi trường)
├── evaluation/    eval_vs_fifa.py (so sự kiện luồng YES với FIFA), check_commentary.py (bảng điểm đoạn demo:
│                  nhịp nói, lặp, tỉ lệ câu LLM, số áo / tên đọc sai qua Whisper)
├── notebooks/     notebook Colab / Kaggle (colab_test_pipeline, colab_video2caption, colab_video2npy, colab_run, kaggle_run)
├── docs/          HUONG_DAN.md, NO_FLOW_SCRIPT.md, assets/
├── CHANGELOG.md
│   (không đưa lên GitHub, xem .gitignore)
├── models/        checkpoint đã train: models/<tên model>/{spotting,caption}/model.pth.tar
├── dataset/       dữ liệu SoccerNet (npy, nhãn)
├── metadata/      kết quả crawl (metadata/fifa/<trận>/*.csv)
└── outputs/       kết quả chạy (timeline, audio...)
```
**Luôn chạy từ thư mục gốc repo**, dạng `python -m <thư mục>.<file>` (không có `.py`), ví dụ:
```sh
python -m crawler.crawl_web --open                 # website crawl metadata
python -m crawler.fifa_crawl --season 2025 --team_a Chelsea --team_b "Manchester City"
python -m deltalab.main --SoccerNet_path dataset/caption-2024 --model_name gpt2-video60-mlp ...
python -m commentary.no_flow_v2 --metadata metadata/fifa/<trận> --events_from_fifa --llm openai ...
python -m voice.tts_v2 --timeline <commentary_timeline.json> --engine openai ...
python -m evaluation.check_commentary --timeline <commentary_timeline.json> --audio_timeline <audio_timeline.json> ...
```

## Introduction
This repository contains the code and models for our SoccerNet 2024 Dense Video Captioning submission from [DeLTA Lab](https://sites.google.com/view/jmkang/about-our-lab). The project leverages a BLIP-2 like architecture with GPT-2 model as a language model.

## Model Architecture
![Model architecture](https://raw.githubusercontent.com/gladuz/soccernet-caption-deltalab/main/assets/architecture.png)
We adapted a framework similar to the BLIP-2 model with the following components:
- **Transformer Decoder**: 4 layers, D = 512, 8 trainable query tokens.
- **Visual Features**: Pre-extracted by Baidu team, window size T = 30.
- **Language model**: GPT2-base and GPT-medium models


## Key Contributions of our solution
- End-to-end training with LLM and vision encoder instead of freezing the LLM weights.
- Changed the spotting action confidence task from binary to multi-class softmax classification.
- Discarded spotted actions with low confidences in localization.
- Combined generated captions from different models and removed overlapping actions.

## Installation
1. Clone the repository:
    ```sh
    git clone https://github.com/gladuz/soccernet-caption-delta.git
    cd soccernet-caption-delta
    ```
2. Create environment similar to [sn-caption baseline](https://github.com/SoccerNet/sn-caption/tree/main/Benchmarks/TemporallyAwarePooling):
    ```sh
    conda create -y -n soccernet-DVC python=3.8
    conda activate soccernet-DVC
    conda install -y pytorch torchvision torchtext pytorch-cuda -c pytorch -c nvidia
    pip install SoccerNet matplotlib scikit-learn spacy wandb
    pip install git+https://github.com/Maluuba/nlg-eval.git@master
    python -m spacy download en_core_web_sm
    pip install torchtext

    # only additional package is tiktoken and transformers used for GPT-2
    pip install tiktoken transformers

    # test pipeline: features/cut_halves.py (PyAV) and the no flow with the ElevenLabs LLM (commentary/no_flow_llm.py)
    pip install av websockets
    ```

## Downloading dataset - refer to the [Soccernet's main captioning repository](https://github.com/SoccerNet/sn-caption)
First install `Soccernet` package using pip.
```bash
pip install SoccerNet
```
Then download the pre-extracted features from Baidu team. Note: the features seems to be at 1fps. We only use the extracted features in our solution.
```python
from SoccerNet.Downloader import SoccerNetDownloader as SNdl
mySNdl = SNdl(LocalDirectory="path/to/SoccerNet")
mySNdl.downloadDataTask(task="caption-2024", split=["train","valid", "test","challenge"]) # SN challenge 2024
```


## Train the model
```bash
python -m deltalab.main --SoccerNet_path=path/to/SoccerNet/  \
--model_name gpt2-train \
--GPU 0 \
--pool QFormer \
--gpt_type gpt2 \
--NMS_threshold 0.7
```
Replace `path/to/SoccerNet` with the local path for Soccernet dataset's `caption-2024` folder. Other options are listed in `deltalab/main.py`. The results should be around 26 in METEOR.

|                  | Bleu_1  | Bleu_2  | Bleu_3  | Bleu_4  | CIDEr  | METEOR  |
|------------------|---------|---------|---------|---------|--------|---------|
| Loose Test Value | 0.39636 | 0.32699 | 0.28424 | 0.25013 | 0.49509| 0.25932 |

## Main parameters
- `--gpt_type`: language model. `gpt2` or `gpt2-medium`. It will load the weights from huggingface by default.
- `--NMS_threshold`: discarding threshold for confidence levels. 
- `--NMS_window`: window of maximum supression. Only the highest confidence actions will be selected within that timeframe.

## Acknowledgements
Codebase is adopted from Soccernet team's baseline https://github.com/SoccerNet/sn-caption

GPT2 model code is from Andrej Karpathy's awesome [nanoGPT repo](https://github.com/karpathy/nanoGPT).

We would like to thank the SoccerNet team for organizing the challenge and providing the datasets. Special thanks to the Baidu team for the pre-extracted visual features.
