# 실검 — 구글 트렌드 기반 실시간 급상승 검색어

구글 트렌드 '급상승 검색어' 데이터를 20분마다 받아서 순위 페이지, 검색어별 페이지, 날짜별 기록 페이지를 자동으로 만드는 사이트입니다.
GitHub Pages로 서버비 없이 운영합니다.

## 폴더 구성

| 파일 | 역할 |
|---|---|
| `build.py` | 데이터 수집 + 사이트 생성 (Python 표준 라이브러리만 사용) |
| `config.json` | 사이트 이름, 문의 이메일, 애드센스 ID 등 설정 |
| `static/` | 디자인(`style.css`)과 동작(`app.js`) |
| `data/` | 쌓이는 기록. **지우면 지금까지의 기록이 사라집니다** |
| `site/` | 만들어진 결과물 (업로드 안 함, 매번 새로 생성) |
| `.github/workflows/build.yml` | 20분마다 자동 실행하는 설정 |

## 내 컴퓨터에서 미리 보기

```powershell
py build.py
py -m http.server 8000 -d site
```
브라우저에서 http://localhost:8000 을 엽니다.

## 인터넷에 올리기 (처음 한 번)

1. **GitHub 가입**: https://github.com
2. **새 저장소 만들기**: 오른쪽 위 `+` → `New repository`
   - 이름은 자유 (예: `silgeom`)
   - **Public**으로 만들어야 GitHub Pages가 무료입니다
3. **파일 올리기**: [GitHub Desktop](https://desktop.github.com)을 설치해 이 폴더(`실시간검색어`)를 저장소로 추가하고 `Publish`.
   (웹에서 `uploading an existing file`로 끌어다 놓아도 되지만, 숨김 폴더인 `.github`가 빠지지 않았는지 꼭 확인하세요.)
4. **Pages 켜기**: 저장소 `Settings` → `Pages` → `Source`를 **GitHub Actions**로 선택
5. **첫 실행**: `Actions` 탭 → `실검 업데이트` → `Run workflow`
   - 몇 분 뒤 `https://<아이디>.github.io/<저장소이름>/` 에서 사이트가 열립니다
   - 이후로는 20분마다 자동으로 갱신됩니다 (GitHub 사정에 따라 늦어지거나 가끔 건너뛸 수 있음)

실행이 '기록 저장' 단계에서 실패하면: `Settings` → `Actions` → `General` → `Workflow permissions`를 **Read and write permissions**로 바꾸세요.

## 애드센스 신청 전에 할 일

1. **도메인 연결 (사실상 필수)**: 애드센스는 사이트의 최상위 주소에 `ads.txt`가 있어야 하는데,
   `아이디.github.io/저장소이름/` 같은 하위 주소로는 이 조건을 맞추기 어렵습니다.
   도메인(예: `silgeom.kr`)을 산 뒤 `Settings` → `Pages` → `Custom domain`에 입력하고, 도메인 업체에서 DNS를 GitHub 안내대로 설정하세요.
2. **`config.json` 채우기**
   - `contactEmail`: 문의 받을 이메일 (문의·개인정보처리방침 페이지에 표시됨)
   - `siteName`: 사이트 이름
3. **기록 쌓기**: 검색어 페이지가 수백 개 쌓인 뒤(2~4주 정도) 신청하는 편이 승인에 유리합니다.
4. **검색엔진 등록**: [Google Search Console](https://search.google.com/search-console)과 [네이버 서치어드바이저](https://searchadvisor.naver.com)에 사이트를 등록하고 `sitemap.xml` 주소를 제출하세요.
5. **애드센스 신청**: https://adsense.google.com
   - 승인 후 받은 게시자 ID(`ca-pub-로 시작하는 값`)를 `config.json`의 `adsenseClient`에 넣고 올리면
     모든 페이지에 광고 코드가 들어가고 `ads.txt`가 자동으로 생깁니다.
   - 광고 위치는 애드센스의 **자동 광고**가 알아서 정합니다.

## 알아둘 점

- 검색량은 구글이 주는 대략치(100+, 500+ 등)입니다.
- 관련 뉴스는 제목과 링크만 싣습니다. 기사 본문이나 사진을 복사해 넣지 마세요(저작권).
- 구글 트렌드 데이터 이용 조건은 Google 서비스 약관을 따릅니다. 사이트에 출처를 표시해 두었습니다.
