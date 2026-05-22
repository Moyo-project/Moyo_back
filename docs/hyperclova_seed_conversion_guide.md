# HyperCLOVA X SEED 0.5B 온디바이스 변환 및 적용 가이드

프론트엔드(브라우저) 환경에서 `Transformers.js`를 사용해 HyperCLOVA X SEED 0.5B를 구동하려면, 기존 PyTorch 기반의 모델을 **웹 브라우저에서 실행 가능한 ONNX 포맷**으로 변환하고 **양자화(Quantization)** 과정을 거쳐야 합니다.

## 1. 무엇을 변환해야 하나요?

Hugging Face에 공개된 원본 모델(`naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-0.5B`)은 PyTorch 환경용 모델입니다. 
브라우저 환경(Transformers.js)에서는 이 원본 모델을 직접 읽을 수 없으므로 다음의 파일들로 변환하여 서빙해야 합니다.

*   **ONNX 모델 파일 (`.onnx`)**: 신경망 모델의 구조와 가중치를 브라우저 엔진(WASM/WebGPU)이 이해할 수 있는 공통 규격으로 변환한 파일입니다. 텍스트 생성 모델의 경우 `model.onnx`, `model_with_past.onnx` 형태의 파일이 생성됩니다.
*   **설정 및 토크나이저 파일 (`.json`)**: `config.json`, `tokenizer.json`, `tokenizer_config.json` 등 텍스트를 모델이 이해하는 토큰으로 쪼개거나 합치는 규칙 파일들도 함께 프론트엔드로 복사해야 합니다.

## 2. 어떻게 변환하나요? (변환 절차)

Python 환경에서 Hugging Face의 `optimum` 라이브러리를 사용하여 변환합니다. 브라우저의 메모리 한계를 고려하여 **양자화(Quantization, 예: q4 혹은 q8)**를 적용해 모델 용량을 대폭 줄이는 것이 핵심입니다.

### Step 1: 변환 도구 설치
로컬 PC나 서버의 터미널(Python 환경)에서 변환에 필요한 패키지를 설치합니다.
```bash
pip install optimum[onnxruntime] transformers
```

### Step 2: ONNX 포맷 변환 및 양자화
`optimum-cli` 명령어를 사용하여 원본 모델을 다운로드하고 ONNX 포맷으로 변환(Export)합니다.
`--task text-generation-with-past` 옵션을 주어 이전 문맥(KV-Cache)을 기억하면서 텍스트를 생성하도록 최적화합니다.

```bash
optimum-cli export onnx \
  --model naver-hyperclovax/HyperCLOVAX-SEED-Text-Instruct-0.5B \
  --task text-generation-with-past \
  --weight-format int8 \
  ./seed_onnx_model/
```
*(참고: `--weight-format int8` 또는 `fp16` 등의 옵션으로 용량을 최적화합니다. Transformers.js에서는 보통 q4, q8 양자화를 권장합니다.)*

### Step 3: 프론트엔드 정적(Static) 폴더로 복사
변환이 완료되면 `./seed_onnx_model/` 폴더 내부에 `.onnx` 파일과 `.json` 파일들이 생성됩니다.
이 폴더를 Moyo 프론트엔드 프로젝트의 `public/` 디렉토리 아래(예: `public/models/seed_onnx_model/`)로 복사합니다.

## 3. 프론트엔드(React)에서 어떻게 사용하나요?

`Transformers.js`를 이용해 브라우저에서 변환된 ONNX 모델을 로드하고 실행합니다.

### 1) 라이브러리 설치
```bash
npm install @huggingface/transformers
```

### 2) React 코드 구현 (`src/agent/nlp/onDeviceClassifier.ts` 예시)
브라우저 메인 스레드가 멈추지 않도록 Web Worker를 사용하는 것이 좋으나, 직관적인 사용 예시는 다음과 같습니다.

```typescript
import { pipeline, env } from "@huggingface/transformers";

// (선택) 로컬 public 폴더에서 모델을 읽어오도록 설정
env.allowLocalModels = true;
// 만약 다른 서버(CDN)에 모델을 올렸다면 URL을 지정
// env.remoteModels = "https://your-domain.com/models/";

export async function loadSeedModel() {
  console.log("HyperCLOVA X SEED 로딩 중...");
  
  // 'text-generation' 파이프라인 생성, 로컬 경로('models/seed_onnx_model') 지정
  const generator = await pipeline(
    "text-generation",
    "models/seed_onnx_model", 
    {
      device: "webgpu", // 또는 "wasm". WebGPU 지원 브라우저에서는 훨씬 빠름
      dtype: "q8"       // 양자화 타입
    }
  );
  
  return generator;
}

export async function testGeneration(generator: any) {
  const messages = [
    { role: "system", content: "당신은 Moyo 그룹 채팅을 보조하는 유용한 AI입니다." },
    { role: "user", content: "오늘 점심 뭐 먹지? 피자랑 치킨 중에 추천해줘." }
  ];
  
  // 채팅 형태를 모델 입력 프롬프트로 변환
  const prompt = generator.tokenizer.apply_chat_template(messages, { tokenize: false, add_generation_prompt: true });
  
  const output = await generator(prompt, {
    max_new_tokens: 50,
    temperature: 0.7,
  });
  
  console.log("생성 결과:", output);
  return output;
}
```

## 요약

1. **`optimum-cli`**를 이용해 PyTorch 원본 모델을 **ONNX 포맷(int8/fp16 양자화 포함)**으로 변환합니다.
2. 생성된 ONNX 및 JSON 파일 묶음을 React 프로젝트의 **`public/` (정적 서빙 폴더)**나 외부 CDN에 배치합니다.
3. **`@huggingface/transformers`** 라이브러리의 `pipeline` 함수를 사용해 브라우저 환경(WebGPU 권장)에서 모델을 호출합니다.
