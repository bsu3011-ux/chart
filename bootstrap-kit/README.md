# Bootstrap Kit

`chart` 의 자동배포 패턴(로컬 Edit → push → GitHub webhook → Oracle 자동 반영)을
다른 레포에 그대로 이식하기 위한 키트.

## 현재 포함된 프로젝트

| 디렉토리 | 대상 레포 | 포트 |
|---|---|---|
| `allersafe/` | `<your-org>/allersafe` | 5001 |

## 사용 방법

### 1. 키트 파일을 대상 레포로 복사

```bash
# 이 chart 레포 안에서
cp -r bootstrap-kit/allersafe/* /path/to/allersafe/
cp -r bootstrap-kit/allersafe/.gitignore /path/to/allersafe/

# 또는 한 줄로 (rsync 사용)
rsync -a bootstrap-kit/allersafe/ /path/to/allersafe/
```

### 2. 대상 레포에 commit & push

```bash
cd /path/to/allersafe
git add .
git commit -m "feat: 자동배포 부트스트랩 추가 (chart 패턴 이식)"
git push origin main
```

### 3. Oracle 1회 셋업

`bootstrap-kit/INSTALL_ON_ORACLE.md` 를 SSH 가능한 사람에게 전달.
약 5~10분이면 끝남.

### 4. 그 후

- 사용자/Claude 누구든 `git push origin main` 만으로 운영 반영
- Oracle 직접 접근 더 이상 필요 없음
- 일상 작업은 `bash claude-apply.sh` (로컬) + `git push` (운영)
