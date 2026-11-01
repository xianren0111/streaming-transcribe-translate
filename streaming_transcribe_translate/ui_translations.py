"""Chinese source text with English, Japanese and Korean interface translations."""


_ROWS = """
正在下载并校验说话人模型，请等待…|Downloading and verifying the speaker model. Please wait…|話者モデルをダウンロード・検証中です。お待ちください…|화자 모델 다운로드 및 검증 중입니다. 기다려 주세요…
说话人模型已就绪，区分说话人已开启。|Speaker model ready. Speaker tracking is enabled.|話者モデルの準備が完了し、話者区別が有効になりました。|화자 모델 준비 완료. 화자 구분이 켜졌습니다.
说话人模型下载失败，未开启。请检查网络后重试。|Speaker model download failed; tracking remains off. Check your connection and retry.|話者モデルのダウンロードに失敗しました。未有効です。接続を確認して再試行してください。|화자 모델 다운로드 실패. 화자 구분은 꺼져 있습니다. 연결 확인 후 다시 시도하세요.
拟声词语义过滤 · 使用翻译 API 判断中日英整句拟声词及语气声，增加费用和延迟，等待整句后显示|Semantic sound filtering · Translation API classifies Chinese/Japanese/English sound-only utterances and interjections; adds cost and latency, displays after the full sentence|擬音語の意味判定 · 翻訳APIで中日英の擬音語・感動詞だけの文を判定。費用と遅延が増え、文の完了後に表示|의성어 의미 필터 · 번역 API로 중일영 의성어와 감탄사만 있는 문장 판별. 비용과 지연 증가, 문장 완료 후 표시
拟声词语义判断不可用，暂时仅使用词表；未确定的内容保留翻译。|Semantic sound classification unavailable; using the word list temporarily and translating uncertain content.|擬音語の意味判定が利用できません。一時的に単語リストのみ使用し、不明な内容は翻訳します。|의성어 의미 판별 불가. 임시로 단어 목록만 사용하며 불확실한 내용은 번역합니다.
说话人识别失败，请关闭区分说话人或重新下载模型后重试。|Speaker identification failed. Disable speaker tracking or download the model again before retrying.|話者識別に失敗しました。話者区別を無効にするかモデルを再ダウンロードして再試行してください。|화자 식별 실패. 화자 구분을 끄거나 모델을 다시 다운로드한 후 재시도하세요.
区分说话人|Distinguish speakers|話者を区別|화자 구분
区分说话人 · 默认关闭，仅字幕和记录显示标签；短句或多人重叠可能分错，停止字幕后修改|Distinguish speakers · Off by default; labels only in subtitles and records. Short or overlapping speech may be misclassified; stop subtitles to change|話者を区別 · 既定は無効。字幕・記録のみラベル表示。短い発話や重なりは誤判定の可能性。変更前に字幕を停止|화자 구분 · 기본 꺼짐, 자막과 기록에만 표시. 짧거나 겹치는 음성은 오인할 수 있음. 변경 전 자막 중지
首次开启将下载约 28 MB 本机声纹模型。音频不上传，下载期间请等待。标签不加入弹幕。继续吗？|First use downloads a local speaker model (~28 MB). Audio is not uploaded. Please wait during download. Labels are not sent to chat. Continue?|初回はローカル話者モデル約28 MBをダウンロード。音声は送信しません。完了までお待ちください。チャットにラベルは付けません。続行しますか？|최초 사용 시 로컬 화자 모델 약 28 MB를 다운로드합니다. 음성은 업로드하지 않습니다. 완료까지 기다려 주세요. 채팅에는 라벨을 붙이지 않습니다. 계속할까요?
请先停止字幕再修改说话人设置。|Stop subtitles before changing speaker settings.|話者設定を変更する前に字幕を停止してください。|화자 설정 변경 전에 자막을 중지하세요.
请先在设置中下载说话人模型。|Download the speaker model in Settings first.|先に設定で話者モデルをダウンロードしてください。|먼저 설정에서 화자 모델을 다운로드하세요.
说话人模型返回了无效声纹。|The speaker model returned an invalid embedding.|話者モデルが無効な声紋を返しました。|화자 모델이 유효하지 않은 임베딩을 반환했습니다.
下载说话人模型失败|Speaker model download failed|話者モデルのダウンロード失敗|화자 모델 다운로드 실패
下载说话人模型|Download speaker model|話者モデルをダウンロード|화자 모델 다운로드
首次开启需确认下载约 28 MB 本机声纹模型。|Confirm the local speaker model download (~28 MB) before first use.|初回利用前に約28 MBの話者モデルのダウンロードを確認してください。|최초 사용 전에 약 28 MB 로컬 화자 모델 다운로드를 확인하세요.
忽略拟声词 · 仅跳过整句笑声、叫声或常见拟声词，不翻译或发送|Ignore sound words · Skip sound-only laughter, calls and common onomatopoeia; do not translate or send|擬音語を無視 · 笑い声・鳴き声・既知の擬音語だけの文は翻訳・送信しない|의성어 무시 · 웃음소리, 울음소리, 일반 의성어만 있는 문장은 번역하거나 보내지 않음
使用当前界面语言的默认模板|Use the default template for this UI language|現在の表示言語の既定テンプレートを使う|현재 UI 언어의 기본 템플릿 사용
发送模板不能为空。|Chat template cannot be empty.|送信テンプレートは空にできません。|전송 템플릿은 비워 둘 수 없습니다.
模板格式不正确，仅支持 {translation}、{original}、{language}。|Invalid template. Use only {translation}, {original}, {language}.|テンプレートが無効です。{translation}・{original}・{language}のみ使用できます。|템플릿 형식이 잘못되었습니다. {translation}, {original}, {language}만 사용할 수 있습니다.
模板必须包含一次 {translation}。|Template must contain {translation} exactly once.|テンプレートには{translation}を1回含めてください。|템플릿에는 {translation}이 정확히 한 번 포함되어야 합니다.
请选择有效的发送语言。|Choose a valid sending language.|有効な送信言語を選択してください。|유효한 전송 언어를 선택하세요.
发送语言必须包含在阅读语言中。|The sending language must be selected for reading.|送信言語は読む言語から選択してください。|전송 언어는 읽을 언어에 포함되어야 합니다.
字幕记录会话丢失，未发送消息；请重新开始字幕。|Recording session missing. Message not sent; restart subtitles.|記録セッションがありません。未送信です。字幕を再開始してください。|기록 세션이 없습니다. 메시지를 보내지 않았습니다. 자막을 다시 시작하세요.
上一条消息已部分发送；请先用原内容重试，避免重复发送。|The previous message was partially sent. Retry its unchanged text first to avoid duplicates.|前のメッセージは一部送信済みです。重複を避けるため元の文で再試行してください。|이전 메시지가 일부 전송되었습니다. 중복을 피하려면 먼저 원래 내용으로 재시도하세요.
审核和发送语言|Review and send language|確認・送信する言語|검토 및 전송 언어
发送模板|Chat template|送信テンプレート|전송 템플릿
模板支持 {translation}、{original}、{language}；修改仅用于新译文，当前审核文字不变。|Use {translation}, {original}, {language}. Changes apply to new translations, not the current draft.|{translation}・{original}・{language}が使えます。変更は新しい訳文に適用され、現在の確認文は変わりません。|{translation}, {original}, {language}를 사용할 수 있습니다. 변경은 새 번역에 적용되며 현재 초안은 유지됩니다.
阅读语言可多选，同时显示多语言字幕；审核和发送仅使用一种语言。停止字幕后可修改语言。|Select multiple reading languages for subtitles. Review and send one language only. Stop subtitles to change languages.|読む言語を複数選択し、字幕を同時表示します。確認・送信は1言語のみ。変更は字幕停止後に行います。|읽을 언어를 여러 개 선택해 자막을 함께 표시합니다. 검토 및 전송은 한 언어만 사용합니다. 자막 중지 후 변경하세요.
超长自动拆分 · 每条上限 |Auto-split long messages · Per-message limit |長文は自動分割・1件の上限 |긴 메시지 자동 분할 · 메시지당 제한
 · 至少间隔 | · Minimum interval |・最小間隔 | · 최소 간격
 秒。应用使用保守限制；房间慢速模式或账号限制可能更严格，网站拒绝时停止发送。| seconds. Conservative app limits; room slow mode or account restrictions may be stricter. Sending stops if the site rejects a message.|秒。アプリの保守的な制限です。ルームやアカウントの制限が厳しい場合があります。拒否されたら送信を停止します。|초. 앱의 보수적 제한입니다. 방 저속 모드나 계정 제한이 더 엄격할 수 있으며 사이트 거부 시 전송을 중단합니다.
请选择有效且不重复的字幕语言。|Choose valid, unique subtitle languages.|有効な字幕言語を重複なく選択してください。|유효한 자막 언어를 중복 없이 선택하세요.
请至少选择一种字幕语言。|Choose at least one subtitle language.|字幕言語を少なくとも1つ選択してください。|자막 언어를 하나 이상 선택하세요.
请先停止字幕|Stop subtitles first|先に字幕を停止してください|먼저 자막을 중지하세요
停止当前字幕后再修改阅读语言。|Stop the current session before changing reading languages.|字幕を停止してから読む言語を変更してください。|현재 자막을 중지한 뒤 읽을 언어를 변경하세요.
阅读语言可多选：同时显示多语言字幕，每种语言单独审核和发送。停止字幕后可修改。|Select multiple reading languages: show all subtitles together, review and send each language separately. Change after stopping subtitles.|読む言語を複数選択できます。字幕を同時表示し、言語ごとに確認・送信します。変更は字幕停止後に行えます。|읽을 언어를 여러 개 선택할 수 있습니다. 자막은 함께 표시하며 언어별로 검토하고 전송합니다. 자막 중지 후 변경할 수 있습니다.
保留数量|Retain|保持数|유지 개수
Final Cut Pro / 剪映：已审核字幕导出|Final Cut Pro / CapCut: export reviewed subtitles|Final Cut Pro / CapCut：確認済み字幕の出力|Final Cut Pro / CapCut: 검토한 자막 내보내기
导出已审核 SRT + CSV|Export reviewed SRT + CSV|確認済みSRT＋CSVを出力|검토한 SRT + CSV 내보내기
时间轴自动从开始字幕时计时。导出已发送和已跳过字幕，使用审核后的文字；CSV 标明发送或跳过。|The timeline starts when subtitles start. Export sent and skipped captions using reviewed text; CSV labels sent or skipped.|字幕開始時から計時します。送信・スキップした字幕を確認後の文で出力し、CSVに状態を記載します。|자막 시작부터 시간을 측정합니다. 전송 및 건너뛴 자막을 검토한 문구로 내보내며 CSV에 상태를 표시합니다.
还没有已发送或已跳过的字幕，请先发送或跳过一条字幕。|No reviewed captions yet. Send or skip a caption first.|確認済み字幕はありません。字幕を送信またはスキップしてください。|아직 검토한 자막이 없습니다. 먼저 자막을 전송하거나 건너뛰세요.
请选择有已发送或已跳过字幕的会话。|Choose a session with sent or skipped captions.|送信またはスキップした字幕があるセッションを選択してください。|전송하거나 건너뛴 자막이 있는 세션을 선택하세요.
还没有已发送或已跳过的字幕，不能导出。|No sent or skipped captions to export.|送信またはスキップした字幕がないため出力できません。|전송하거나 건너뛴 자막이 없어 내보낼 수 없습니다.
字幕都在会话开始之前；CSV 已导出，请检查会话时间。|All captions precede session start. CSV exported; check the session time.|全字幕がセッション開始前です。CSVは出力済みです。時刻を確認してください。|모든 자막이 세션 시작 전입니다. CSV는 내보냈습니다. 세션 시간을 확인하세요.
没有可导出的字幕记录。|No caption records to export.|出力できる字幕記録がありません。|내보낼 자막 기록이 없습니다.
字幕记录的审核状态无效。|Invalid caption review status.|字幕記録の確認状態が無効です。|자막 기록의 검토 상태가 올바르지 않습니다.
记录保存文件夹|Record save folder|記録の保存フォルダー|기록 저장 폴더
选择文件夹|Choose folder|フォルダーを選択|폴더 선택
选择记录保存文件夹|Choose record save folder|記録の保存フォルダーを選択|기록 저장 폴더 선택
请选择完整的记录文件夹路径。|Choose an absolute record folder path.|記録フォルダーの絶対パスを選択してください。|기록 폴더의 절대 경로를 선택하세요.
请选择有效的记录文件夹。|Choose an existing record folder.|既存の記録フォルダーを選択してください。|존재하는 기록 폴더를 선택하세요.
文件夹选择自动保存，从下次开始字幕生效；当前会话保留在原文件夹，不移动已有记录。|The folder choice is saved automatically and applies to the next session. The current session stays in its original folder; existing records are not moved.|フォルダーは自動保存され、次回の字幕開始から適用されます。現在のセッションと既存の記録は元の場所に残ります。|폴더 선택은 자동 저장되며 다음 세션부터 적용됩니다. 현재 세션과 기존 기록은 원래 폴더에 유지됩니다.
发送成功或跳过时保存原文和当前译文|Save original and current translation on successful Send or Skip|送信成功・スキップ時に原文と現在の訳文を保存|전송 성공 또는 건너뛰기 시 원문과 현재 번역 저장
记录原文、翻译提示词、译文和 Decisions 问答（不含音频或 key）|Log originals, translation prompts, translations and Decisions answers (no audio or keys)|原文・翻訳プロンプト・訳文・Decisions回答を記録（音声・キーを除く）|원문, 번역 프롬프트, 번역 및 Decisions 응답 기록(오디오/키 제외)
发送成功或跳过时保存原文和当前译文（下次开始字幕生效）|Save original and current translation on successful Send or Skip (next session)|送信成功・スキップ時に原文と現在の訳文を保存（次回から）|전송 성공 또는 건너뛰기 시 원문과 현재 번역 저장(다음 세션부터)
记录未保存|Record not saved|記録が保存されませんでした|기록이 저장되지 않았습니다
跳过记录保存失败；已保留当前内容，请检查磁盘空间后重试。|Could not save the skipped item. Your text is kept; check disk space and retry.|スキップした項目を保存できません。内容は保持されています。空き容量を確認して再試行してください。|건너뛴 항목을 저장하지 못했습니다. 내용은 유지됩니다. 디스크 공간을 확인하고 다시 시도하세요.
时间轴自动从开始字幕时计时，无需填写时间。CSV 保留接收和发送时钟；SRT 使用实际发送文字。|The timeline starts automatically when subtitles start. No time entry is needed. CSV keeps receipt/send clocks; SRT uses the text actually sent.|字幕開始時から自動で計時します。時刻入力は不要です。CSVには受信・送信時刻、SRTには実際の送信文を保存します。|자막 시작 시 자동으로 시간을 측정합니다. 시간 입력은 필요 없습니다. CSV는 수신/전송 시각, SRT는 실제 전송 문구를 사용합니다.
电脑声音|Computer sound|PCの音声|컴퓨터 소리
麦克风和电脑声音可直接使用，无需登录。发送聊天才需要账号。|Microphone and computer sound work without login. Sign in only to send chat.|マイクとPCの音声はログイン不要。チャット送信にはログインが必要です。|마이크와 컴퓨터 소리는 로그인 없이 사용합니다. 채팅 전송에만 로그인이 필요합니다.
正在加载语音识别并捕获电脑声音。电脑播放的声音会被识别和翻译。|Loading speech recognition and capturing computer sound. Whatever the computer plays will be recognized and translated.|音声認識を読み込み、PCの音声をキャプチャしています。PCで再生した音声が認識・翻訳されます。|음성 인식을 불러오고 컴퓨터 소리를 캡처하는 중입니다. 컴퓨터에서 재생되는 소리가 인식되고 번역됩니다.
无法捕获电脑声音，请检查播放设备（扬声器/耳机）后重新开始。|Cannot capture computer sound. Check the playback device (speakers/headphones) and start again.|PCの音声をキャプチャできません。再生デバイス（スピーカー/ヘッドホン）を確認して再開してください。|컴퓨터 소리를 캡처할 수 없습니다. 재생 장치(스피커/헤드폰)를 확인한 뒤 다시 시작하세요.
缺少电脑声音组件，请运行 Setup Models.bat 或 pip install soundcard 后重试。|The computer sound component is missing. Run Setup Models.bat or pip install soundcard, then try again.|PC音声コンポーネントがありません。Setup Models.bat または pip install soundcard を実行してから再試行してください。|컴퓨터 소리 구성 요소가 없습니다. Setup Models.bat 또는 pip install soundcard 를 실행한 뒤 다시 시도하세요.
记录未开启|Records are off|記録はオフです|기록이 꺼져 있습니다
请先在「设置 → 记录」打开「保存字幕和发送记录（用于导出时间轴）」并保存；从下次开始字幕起会保存记录。|First turn on "Save subtitle and sent-message records (for timeline export)" in Settings → Records and save. Records are kept from the next subtitle session.|先に「設定 → 記録」で「字幕と送信記録を保存（タイムライン書き出し用）」をオンにして保存してください。次回の字幕開始から記録されます。|먼저 「설정 → 기록」에서 「자막 및 전송 기록 저장(타임라인 내보내기용)」을 켜고 저장하세요. 다음 자막 시작부터 기록됩니다.
保存字幕和发送记录（用于导出时间轴）|Save subtitle and sent-message records (for timeline export)|字幕と送信記録を保存（タイムライン書き出し用）|자막 및 전송 기록 저장(타임라인 내보내기용)
记录默认关闭。开启后，成功发送的消息会保存到本机，用于剪辑导出；关闭时不写入任何记录文件。记录可能包含私人对话，请谨慎分享。|Records are off by default. When on, successfully sent messages are saved on this computer for editing exports; when off, no record files are written. Records may contain private conversations, so share them carefully.|記録は既定でオフです。オンにすると送信に成功したメッセージをこのPCに保存し、編集用に書き出せます。オフの間は記録ファイルを一切書き込みません。記録には私的な会話が含まれる場合があるため、共有には注意してください。|기록은 기본적으로 꺼져 있습니다. 켜면 전송에 성공한 메시지를 이 컴퓨터에 저장해 편집용으로 내보낼 수 있으며, 끄면 기록 파일을 전혀 쓰지 않습니다. 기록에는 사적인 대화가 포함될 수 있으니 공유에 주의하세요.
无法读取已保存的 API Key|Cannot read the saved API key|保存済みの API Key を読み取れません|저장된 API Key를 읽을 수 없습니다
已保存的 API Key 只能由保存它的 Windows 账户解密（可能换了电脑或账户）。请在「设置 → 翻译」重新填写 API Key 并保存。|The saved API key can only be decrypted by the Windows account that saved it (the computer or account may have changed). Re-enter the API key in Settings → Translation and save.|保存済みの API Key は保存した Windows アカウントでしか復号できません（PCまたはアカウントが変わった可能性があります）。「設定 → 翻訳」で API Key を入力し直して保存してください。|저장된 API Key는 저장한 Windows 계정에서만 복호화할 수 있습니다(컴퓨터나 계정이 바뀌었을 수 있습니다). 「설정 → 번역」에서 API Key를 다시 입력하고 저장하세요.
无法加密保存 API Key。|Could not encrypt and save the API key.|API Key を暗号化して保存できませんでした。|API Key를 암호화해 저장할 수 없습니다.
打开字幕悬浮窗|Open floating subtitles|字幕フローティングウィンドウを開く|자막 플로팅 창 열기
关闭字幕悬浮窗|Close floating subtitles|字幕フローティングウィンドウを閉じる|자막 플로팅 창 닫기
解锁悬浮窗|Unlock floating window|フローティングウィンドウのロック解除|플로팅 창 잠금 해제
暂停字幕|Pause subtitles|字幕を一時停止|자막 일시 정지
继续字幕|Resume subtitles|字幕を再開|자막 재개
字幕悬浮窗在此模式下不可用，请使用下面的浏览器字幕页。|Floating subtitles are unavailable in this mode. Use the browser subtitle page below.|このモードでは字幕フローティングウィンドウを使えません。下のブラウザー字幕ページを使ってください。|이 모드에서는 자막 플로팅 창을 사용할 수 없습니다. 아래 브라우저 자막 페이지를 사용하세요.
字幕悬浮窗已锁定（鼠标可穿透）。点「解锁悬浮窗」恢复拖动和工具栏。|Floating subtitles are locked (clicks pass through). Click Unlock floating window to drag it and use the toolbar again.|字幕フローティングウィンドウはロック中です（クリックは透過します）。「フローティングウィンドウのロック解除」でドラッグとツールバーが戻ります。|자막 플로팅 창이 잠겨 있습니다(클릭이 통과됩니다). 「플로팅 창 잠금 해제」를 누르면 끌기와 도구 모음이 돌아옵니다.
悬浮窗始终置顶，可拖动、右下角调整大小；鼠标移入显示工具栏。|The floating window stays on top. Drag to move, resize from the bottom-right corner, and hover to show the toolbar.|フローティングウィンドウは常に最前面です。ドラッグで移動、右下でサイズ変更、マウスを乗せるとツールバーが出ます。|플로팅 창은 항상 위에 표시됩니다. 끌어서 이동하고 오른쪽 아래에서 크기를 조절하며, 마우스를 올리면 도구 모음이 나타납니다.
悬浮窗不可用|Floating window unavailable|フローティングウィンドウは使用できません|플로팅 창을 사용할 수 없습니다
字幕未运行|Subtitles are not running|字幕は実行されていません|자막이 실행 중이 아닙니다
开始字幕后才能暂停。|Start subtitles before pausing.|一時停止するには先に字幕を開始してください。|일시 정지하려면 먼저 자막을 시작하세요.
字幕已继续。|Subtitles resumed.|字幕を再開しました。|자막을 재개했습니다.
字幕已暂停，点「继续字幕」恢复。|Subtitles paused. Click Resume subtitles to continue.|字幕を一時停止しました。「字幕を再開」で再開します。|자막을 일시 정지했습니다. 「자막 재개」를 눌러 계속하세요.
字号|Text size|文字サイズ|글자 크기
背景|Background|背景|배경
原文|Original|原文|원문
用时|Timing|所要時間|소요 시간
暂停|Pause|一時停止|일시 정지
锁定|Lock|ロック|잠금
解锁|Unlock|ロック解除|잠금 해제
已暂停|Paused|一時停止中|일시 정지됨
正在听…|Listening…|聞き取り中…|듣는 중…
智能断句 · 暂停时判断是否说完，最多额外等待 1 秒|Smart segmentation · Up to 1s extra pause wait|スマート区切り · 最大 1 秒追加待機|스마트 문장 분할 · 최대 1초 추가 대기
语音识别模型尚未安装，请先双击「Setup Models.bat」完成安装。|Speech recognition models are not installed. Double-click "Setup Models.bat" first.|音声認識モデルが未インストールです。先に「Setup Models.bat」をダブルクリックしてください。|음성 인식 모델이 설치되지 않았습니다. 먼저 「Setup Models.bat」을 더블클릭하세요.
检测模型|Detect models|モデルを検出|모델 감지
其他（手动输入）…|Other (type it in)…|その他（手入力）…|기타(직접 입력)…
检测完成，请从下拉列表选择模型。模型数量：|Detected. Pick a model from the dropdown. Models: |検出完了。プルダウンからモデルを選んでください。モデル数：|감지 완료. 드롭다운에서 모델을 선택하세요. 모델 수: 
正在检测…|Detecting…|検出中…|감지 중…
正在读取模型列表…|Reading model list…|モデル一覧を取得中…|모델 목록을 읽는 중…
检测失败：|Detection failed: |検出失敗：|감지 실패: 
检测完成，可从「模型 ID」列表选择。模型数量：|Done. Choose from the Model ID list. Models found: |検出完了。「モデル ID」一覧から選択してください。モデル数：|감지 완료. 「모델 ID」 목록에서 선택하세요. 모델 수: 
填好服务地址（和 API Key）后点「检测模型」，即可从列表中选择。|Enter the service URL (and API key), then click Detect models to pick from a list.|サービスURL（とAPI Key）を入力し「モデルを検出」を押すと一覧から選べます。|서비스 URL(및 API Key)을 입력한 뒤 「모델 감지」를 누르면 목록에서 선택할 수 있습니다.
API Key 无效或没有权限读取模型列表。|API key is invalid or cannot read the model list.|API Keyが無効か、モデル一覧を読む権限がありません。|API Key가 잘못되었거나 모델 목록을 읽을 권한이 없습니다.
此服务地址不支持读取模型列表，请手动填写模型 ID。|This service does not provide a model list. Enter the model ID manually.|このサービスはモデル一覧に対応していません。モデルIDを手動で入力してください。|이 서비스는 모델 목록을 제공하지 않습니다. 모델 ID를 직접 입력하세요.
服务返回的模型列表格式无法识别。|The service returned a model list in an unknown format.|モデル一覧の形式を認識できません。|모델 목록 형식을 인식할 수 없습니다.
服务没有返回任何模型。|The service returned no models.|サービスからモデルが返されませんでした。|서비스가 모델을 반환하지 않았습니다.
服务没有返回模型列表。|The service did not return a model list.|サービスがモデル一覧を返しませんでした。|서비스가 모델 목록을 반환하지 않았습니다.
连接翻译服务超时，请检查服务地址。|Connection to the translation service timed out. Check the URL.|翻訳サービスへの接続がタイムアウトしました。URLを確認してください。|번역 서비스 연결 시간이 초과되었습니다. URL을 확인하세요.
无法连接翻译服务，请检查服务地址和网络。|Cannot reach the translation service. Check the URL and network.|翻訳サービスに接続できません。URLとネットワークを確認してください。|번역 서비스에 연결할 수 없습니다. URL과 네트워크를 확인하세요.
读取模型列表失败。|Could not read the model list.|モデル一覧を取得できませんでした。|모델 목록을 읽지 못했습니다.
服务返回错误（HTTP |Service returned an error (HTTP |サービスエラー（HTTP |서비스 오류(HTTP 
开启后会把原文/译文发给 OpenCode Zen，不发送音频。网络失败会明确提示并跳过辅助。|Sends original/translated text to OpenCode Zen, not audio. Network failures are reported; assistance is bypassed.|原文・訳文をOpenCode Zenへ送信します。音声は送信しません。接続失敗は通知し補助をスキップします。|원문/번역문을 OpenCode Zen으로 전송하며 음성은 전송하지 않습니다. 네트워크 오류를 알리고 지원을 건너뜁니다.
翻译服务响应超时，模型可能仍在加载或处理长文本。请检查模型速度和系统资源后重试。|Translation response timed out. The model may still be loading or processing long text. Check model speed and system resources, then retry.|翻訳応答がタイムアウトしました。モデルの読み込みや長文処理が続いている可能性があります。モデル速度とシステムリソースを確認してください。|번역 응답 시간이 초과되었습니다. 모델 로딩 또는 긴 텍스트 처리 중일 수 있습니다. 모델 속도와 시스템 리소스를 확인하세요.
连接翻译服务超时，请确认服务已启动并检查服务地址。|Connection to the translation service timed out. Check that it is running and the URL is correct.|翻訳サービスへの接続がタイムアウトしました。起動状態とURLを確認してください。|번역 서비스 연결 시간이 초과되었습니다. 서비스 실행 상태와 URL을 확인하세요.
YouTube 未指明当前频道，请使用切换账号手动选择。|YouTube did not identify the current channel. Choose an account/channel manually.|YouTubeが現在のチャンネルを特定できません。手動で選択してください。|YouTube에서 현재 채널을 확인하지 못했습니다. 계정/채널을 직접 선택하세요.
切换 YouTube 账号|Change YouTube account/channel|YouTubeアカウント・チャンネル切替|YouTube 계정/채널 변경
请先停止字幕并等待发送完成，再切换账号。|Stop subtitles and wait for sending to finish before switching accounts.|字幕を停止し、送信完了後にアカウントを切り替えてください。|자막을 중지하고 전송이 완료된 후 계정을 변경하세요.
正在读取 YouTube 账号和频道…|Finding YouTube accounts and channels…|YouTubeアカウントとチャンネルを取得中…|YouTube 계정과 채널 검색 중…
选择用于发送聊天的 YouTube 账号或频道。|Choose the YouTube account or channel to send chat as.|チャットを送信するYouTubeアカウントまたはチャンネルを選択してください。|채팅을 전송할 YouTube 계정 또는 채널을 선택하세요.
使用此账号|Use this account|このアカウントを使用|이 계정 사용
无法读取 YouTube 账号，请检查登录状态和网络后重试。|Unable to list YouTube accounts. Check login and network, then retry.|YouTubeアカウントを取得できません。ログインと接続を確認してください。|YouTube 계정을 불러올 수 없습니다. 로그인과 네트워크를 확인하세요.
没有找到可用的 YouTube 账号或频道。|No available YouTube accounts or channels found.|利用可能なYouTubeアカウント・チャンネルがありません。|사용 가능한 YouTube 계정 또는 채널이 없습니다.
请输入有效的直播间链接，不要包含账号密码。|Enter a valid stream URL without embedded credentials.|認証情報を含まない有効な配信URLを入力してください。|인증 정보 없는 올바른 방송 URL을 입력하세요.
不支持此直播间地址；请选择 Bilibili、YouTube 或 MissEvan 的直播链接。|Unsupported URL. Use a Bilibili, YouTube or MissEvan live link.|未対応のURLです。Bilibili・YouTube・MissEvanの配信リンクを使用してください。|지원하지 않는 URL입니다. Bilibili, YouTube 또는 MissEvan 방송 링크를 사용하세요.
请输入 MissEvan 直播间链接或数字房间号。|Enter a MissEvan live URL or numeric room ID.|MissEvan配信URLまたは数字の部屋IDを入力してください。|MissEvan 방송 URL 또는 숫자 방 ID를 입력하세요.
MissEvan Cookie 中没有可用的登录凭证。|No usable MissEvan login cookies.|有効なMissEvanログインCookieがありません。|사용 가능한 MissEvan 로그인 쿠키가 없습니다.
MissEvan 音频连接失败，请确认房间正在直播并检查网络。|MissEvan audio connection failed. Check that the room is live and the network is available.|MissEvan音声接続失敗。配信中であることと接続を確認してください。|MissEvan 오디오 연결 실패. 방송 중인지와 네트워크를 확인하세요.
MissEvan 发送失败，请检查登录状态和直播间权限。|MissEvan send failed. Check login and room permissions.|MissEvan送信失敗。ログインと部屋の権限を確認してください。|MissEvan 전송 실패. 로그인과 방송 권한을 확인하세요.
不支持此登录平台。|Unsupported login platform.|未対応のログイン先です。|지원하지 않는 로그인 플랫폼입니다.
登录验证失败或网络暂时不可用；请重新登录后再试。|Login verification failed or network unavailable. Sign in again and retry.|ログイン確認失敗、または接続不可。再ログインして試してください。|로그인 확인 실패 또는 네트워크 오류. 다시 로그인하고 시도하세요.
背景浓淡必须在 10% 到 100% 之间。|Opacity must be between 10% and 100%.|不透明度は10%～100%にしてください。|불투명도는 10%~100%여야 합니다.
未知的字幕配色或 Decisions 服务。|Unknown subtitle palette or Decisions service.|字幕配色またはDecisionsサービスが不明です。|알 수 없는 자막 색상 또는 Decisions 서비스입니다.
未知的字幕显示方式。|Unknown subtitle display mode.|字幕表示方式が不明です。|알 수 없는 자막 표시 모드입니다.
请选择有效的内容类型。|Select a valid content mode.|有効なモードを選択してください。|올바른 콘텐츠 모드를 선택하세요.
内容背景和术语表格式无效。|Invalid background or glossary format.|背景・用語集の形式が不正です。|배경 또는 용어집 형식이 잘못되었습니다.
字幕设置文件格式无效。|Invalid subtitle settings file.|字幕設定ファイルの形式が不正です。|자막 설정 파일 형식이 잘못되었습니다.
请填写不含账号密码的有效 Decisions 服务地址。|Enter a valid Decisions URL without embedded credentials.|認証情報を含まない有効なDecisions URLを入力してください。|인증 정보가 포함되지 않은 올바른 Decisions URL을 입력하세요.
请填写 Decisions 模型。|Enter a Decisions model.|Decisionsモデルを入力してください。|Decisions 모델을 입력하세요.
请输入录像开始日期和时间，例如 2026-10-31 23:00:00。|Enter the recording start date/time, e.g. 2026-10-31 23:00:00.|録画開始日時を入力してください。例：2026-10-31 23:00:00。|녹화 시작 날짜와 시간을 입력하세요. 예: 2026-10-31 23:00:00.
录像开始时间必须包含完整日期。|Recording start must include a full date.|録画開始には完全な日付が必要です。|녹화 시작에는 전체 날짜가 필요합니다.
还没有成功发送的消息，不能导出已发送字幕。|No successful sends to export.|送信成功のメッセージがないため出力できません。|전송 성공 메시지가 없어 내보낼 수 없습니다.
已发送消息都在录像开始之前；CSV 已导出，请检查录像开始时间后重试 SRT。|All sends precede recording start. CSV exported; correct the start time and retry SRT.|全メッセージが録画開始前です。CSVは出力済み。開始時刻を確認してSRTを再出力してください。|모든 메시지가 녹화 시작 전입니다. CSV는 내보냈습니다. 시작 시간을 수정하고 SRT를 다시 내보내세요.
记录文件的会话编号不匹配。|Session ID mismatch in records.|記録のセッションIDが一致しません。|기록의 세션 ID가 일치하지 않습니다.
请选择有成功发送消息的字幕会话。|Select a session with successful sends.|送信成功のあるセッションを選択してください。|전송 성공 메시지가 있는 세션을 선택하세요.
找不到 Streaming 登录组件；请将 Streaming 文件夹放在本应用旁边。|Streaming login helpers not found. Place the Streaming folder beside this app.|Streamingログイン部品がありません。アプリの隣にStreamingフォルダーを置いてください。|Streaming 로그인 구성 요소가 없습니다. 앱 옆에 Streaming 폴더를 두세요.
Streaming 登录组件缺少依赖；请先按照 Streaming 项目的说明安装依赖。|Streaming login dependencies missing. Install them per the Streaming project instructions.|Streamingのログイン依存が不足しています。プロジェクトの手順でインストールしてください。|Streaming 로그인 종속성이 없습니다. Streaming 프로젝트 지침에 따라 설치하세요.
Firefox 中没有找到该网站的登录 Cookie，请先登录网站。|No login cookies found in Firefox. Sign in there first.|FirefoxにログインCookieがありません。先にサイトへログインしてください。|Firefox에서 로그인 쿠키를 찾을 수 없습니다. 먼저 사이트에 로그인하세요.
没有找到对应网站的 Cookie。|No cookies found for this site.|該当サイトのCookieがありません。|해당 사이트 쿠키를 찾을 수 없습니다.
Bilibili 没有返回有效二维码，请重试。|Bilibili returned no valid QR code. Retry.|Bilibiliから有効なQRコードが返されませんでした。再試行してください。|Bilibili에서 올바른 QR 코드를 반환하지 않았습니다. 다시 시도하세요.
二维码登录连接失败，请检查网络后重试。|QR sign-in connection failed. Check network and retry.|QRログイン接続失敗。ネットワークを確認して再試行してください。|QR 로그인 연결 실패. 네트워크 확인 후 다시 시도하세요.
发送记录属于不同的字幕会话。|Send record belongs to a different session.|送信記録は別のセッションに属しています。|전송 기록이 다른 세션에 속합니다.
不发送|Do not send|送信しない|전송 안 함
已导出：|Exported: |出力済み：|내보냄: 
同传字幕无法启动|Live Subtitles cannot start|同時字幕を開始できません|실시간 자막을 시작할 수 없음
应用初始化失败：|Application initialization failed: |アプリ初期化に失敗：|앱 초기화 실패: 
字幕设置加载失败|Subtitle settings load failed|字幕設定の読込失敗|자막 설정 로딩 실패
字幕设置损坏或无法读取；本次使用默认设置，请检查后重新保存。|Subtitle settings are unreadable. Using defaults; check and save again.|字幕設定が読めません。既定値を使用します。確認して再保存してください。|자막 설정을 읽을 수 없습니다. 기본값을 사용하니 확인 후 다시 저장하세요.
密钥已保存在这台电脑。|Key saved on this computer.|キーをこのPCに保存しました。|이 컴퓨터에 키를 저장했습니다.
已清除 API Key。|API key cleared.|APIキーを削除しました。|API 키를 삭제했습니다.
已清除保存的密钥。|Saved key cleared.|保存済みキーを削除しました。|저장된 키를 삭제했습니다.
开始字幕并保存文本或成功发送消息后，这里会出现记录。|Records appear after saving subtitles or successfully sending messages.|字幕保存またはメッセージ送信成功後に記録が表示されます。|자막 저장 또는 메시지 전송 성공 후 기록이 표시됩니다.
本次仍会开始翻译，但直播间和语言选择无法保存到下次使用。|Translation can start, but room and language choices could not be saved.|翻訳は開始できますが、配信と入力言語を次回用に保存できませんでした。|번역은 시작할 수 있지만 방송 및 언어 선택을 저장하지 못했습니다.
清除 API Key|Clear API key|APIキーを削除|API 키 삭제
清除这台电脑上已保存的 API Key？|Clear the API key saved on this computer?|このPCに保存したAPIキーを削除しますか？|이 컴퓨터에 저장된 API 키를 삭제하시겠습니까?
设置未能保存|Settings not saved|設定を保存できませんでした|설정 저장 실패
请手动打开本应用的 records 文件夹。|Open this app's records folder manually.|アプリのrecordsフォルダーを手動で開いてください。|앱의 records 폴더를 직접 여세요.
还不能开始|Cannot start yet|まだ開始できません|아직 시작할 수 없음
连接成功，翻译服务可以正常使用。|Connected. Translation service is ready.|接続成功。翻訳サービスを利用できます。|연결 성공. 번역 서비스를 사용할 수 있습니다.
请输入 YouTube 直播链接，例如 youtube.com/watch?v=… 或 youtube.com/live/…。|Enter a YouTube live URL, such as youtube.com/watch?v=… or youtube.com/live/….|YouTube配信URLを入力してください（youtube.com/watch?v=… または youtube.com/live/…）。|YouTube 방송 URL을 입력하세요 (youtube.com/watch?v=… 또는 youtube.com/live/…).
请输入 Bilibili 直播间链接或数字房间号。|Enter a Bilibili live URL or numeric room ID.|Bilibili配信URLまたは数字の部屋IDを入力してください。|Bilibili 방송 URL 또는 숫자 방 ID를 입력하세요.
翻译服务拒绝访问，请检查 API Key 和服务地址。|Translation service denied access. Check API key and URL.|翻訳サービスにアクセスを拒否されました。キーとURLを確認してください。|번역 서비스 접근 거부. API 키와 URL을 확인하세요.
无法连接翻译服务，请检查网络和服务地址。|Cannot connect to translation service. Check network and URL.|翻訳サービスに接続できません。ネットワークとURLを確認してください。|번역 서비스 연결 실패. 네트워크와 URL을 확인하세요.
翻译服务返回了无法识别的内容，请检查服务地址和模型。|Unexpected translation response. Check service URL and model.|翻訳応答が不正です。URLとモデルを確認してください。|번역 응답 형식 오류. 서비스 URL과 모델을 확인하세요.
语音识别失败，请检查模型和 GPU 运行库后重试。|ASR failed. Check model and GPU libraries before retrying.|音声認識失敗。モデルとGPUライブラリを確認して再試行してください。|음성 인식 실패. 모델과 GPU 라이브러리를 확인하세요.
字幕处理或记录保存失败，请检查设置和磁盘空间。|Subtitle processing or saving failed. Check settings and disk space.|字幕処理・記録保存に失敗。設定と空き容量を確認してください。|자막 처리 또는 기록 저장 실패. 설정과 디스크 공간을 확인하세요.
译文检查仍有疑问；请手动审核，不会自动发送。|Translation remains uncertain. Review manually; it will not auto-send.|訳文に不確実な点があります。手動確認してください。自動送信はしません。|번역에 의문이 있습니다. 수동 검토하세요. 자동 전송하지 않습니다.
麦克风已断开，请检查设备后重新开始。|Microphone disconnected. Check device and restart.|マイクが切断されました。機器を確認して再開してください。|마이크 연결 끊김. 장치 확인 후 다시 시작하세요.
麦克风录音中断或溢出，请检查设备后重新开始。|Microphone capture interrupted or overflowed. Check device and restart.|マイク録音が中断またはオーバーフロー。機器を確認して再開してください。|마이크 녹음 중단 또는 오버플로. 장치 확인 후 다시 시작하세요.
麦克风音频处理队列已满，请停止后重新开始。|Microphone queue is full. Stop and restart.|マイク処理キューが満杯です。停止して再開してください。|마이크 처리 큐가 가득 찼습니다. 중지 후 다시 시작하세요.
翻译服务处理太慢，待翻译队列已满。请停止后检查翻译服务。|Translation service is too slow; queue full. Stop and check the service.|翻訳サービスが遅く、キューが満杯です。停止してサービスを確認してください。|번역 서비스가 느려 큐가 가득 찼습니다. 중지 후 서비스를 확인하세요.
Cookie 相当于登录凭证。只在本次运行中保存在内存，不会写入配置文件或日志。请勿发送给他人。|Cookies are login credentials. Kept in memory only, never in config or logs. Do not share them.|Cookieはログイン情報です。メモリ内のみ保持し、設定やログには保存しません。他人に渡さないでください。|쿠키는 로그인 정보입니다. 메모리에만 보관하며 설정·로그에 저장하지 않습니다. 공유하지 마세요.
Final Cut Pro / 剪映：已发送消息导出|Final Cut Pro / CapCut: export sent messages|Final Cut Pro / CapCut：送信済みメッセージ出力|Final Cut Pro / CapCut: 전송 메시지 내보내기
主页保留原文、待审核队列和一个可编辑聊天框。灰色字幕是仍可能修订的草稿。|Home shows originals, review queue and one editor. Gray subtitles are revisable drafts.|ホームには原文、確認待ち、編集欄を表示。灰色字幕は修正される可能性のある下書きです。|홈에 원문, 검토 대기, 편집창을 표시합니다. 회색 자막은 수정 가능한 초안입니다.
主页的「字幕窗口」可单独显示字幕并供 OBS 捕获。颜色、字号、透明度和尺寸在「字幕」页设置；窗口可拖动和关闭。|Open Subtitle window for OBS capture. Set colors, font, opacity and size under Subtitles; drag or close the window.|字幕ウィンドウはOBSでキャプチャ可能です。色・文字・透明度・サイズは字幕タブで設定。移動・閉じる操作が可能です。|자막 창은 OBS 캡처가 가능합니다. 색·글꼴·불투명도·크기는 자막 탭에서 설정하며 창 이동·닫기가 가능합니다.
从 Firefox 读取并验证|Read and verify Firefox cookies|Firefoxから読み込んで確認|Firefox 쿠키 읽기 및 확인
使用哔哩哔哩手机 App 扫码登录|Sign in with 哔哩哔哩 mobile QR scan|哔哩哔哩アプリでQRログイン|哔哩哔哩 모바일 앱 QR 로그인
保存|Save|保存|저장
保存已完成的原文和译文（从下次开始字幕生效）|Save finalized originals and translations (next session)|確定原文・訳文を保存（次回から）|확정 원문·번역 저장 (다음 세션부터)
可以粘贴 Cookie 请求头、Netscape 导出或 JSON 格式。|Paste a Cookie header, Netscape export or JSON.|Cookieヘッダー、Netscape出力、JSONを貼り付けできます。|쿠키 헤더, Netscape 내보내기 또는 JSON을 붙여넣으세요.
填入原始录像的系统开始时间。CSV 保留接收时钟、发送时钟、原文、译文和实际发送文字；SRT 只用实际发送文字。|Enter the recording start clock. CSV keeps receipt/send times, originals, translations and sent text; SRT uses sent text only.|録画開始時刻を入力。CSVには受信・送信時刻と原文・訳文・送信文を保持。SRTは送信文のみです。|녹화 시작 시간을 입력하세요. CSV에는 수신·전송 시간, 원문·번역·전송 텍스트를 보관하며 SRT는 전송 텍스트만 사용합니다.
填写一个 OpenAI 兼容的翻译服务。声音识别在本机完成，只有识别出的文字会发送给此服务。|Configure an OpenAI-compatible service. Speech recognition is local; only recognized text is sent.|OpenAI互換サービスを設定。音声認識はローカルで実行し、認識テキストのみ送信します。|OpenAI 호환 서비스를 설정하세요. 음성 인식은 로컬에서 수행하며 인식된 텍스트만 전송합니다.
字幕窗口 · 可在 OBS 中捕获|Subtitle window · OBS capture|字幕ウィンドウ · OBSキャプチャ可能|자막 창 · OBS 캡처 가능
字幕预览：识别和翻译后会显示在这里。|Subtitle preview: recognized and translated text appears here.|字幕プレビュー：認識・翻訳したテキストをここに表示します。|자막 미리 보기: 인식 및 번역된 텍스트가 여기에 표시됩니다.
开启后会把原文/译文发给所选服务，不发送音频。网络失败会明确提示并跳过辅助。|Sends original/translated text, not audio, to the selected service. Network failures are reported; assistance is bypassed.|原文・訳文のみ選択サービスへ送信。音声は送りません。接続失敗は通知し、補助をスキップします。|선택 서비스로 원문·번역만 보내며 음성은 보내지 않습니다. 네트워크 오류는 알리고 지원을 건너뜁니다.
成功发送记录始终保存到本机，用于剪辑导出。跳过或发送失败不计入已发送字幕。记录可能包含私人对话，请谨慎分享。|Successful sends are recorded locally for editing. Skips/failures are excluded. Records may contain private speech; share carefully.|送信成功の記録を編集用に保存。スキップ・失敗は除外します。私的な会話を含むため共有に注意してください。|전송 성공 기록은 편집용으로 로컬 저장합니다. 건너뛰기·실패는 제외합니다. 개인 대화가 포함될 수 있으니 공유에 주의하세요.
记录每次使用：原文、翻译提示词、译文、Decisions 问答（不含音频或 key；下次生效）|Log originals, prompts, translations and Decisions answers (no audio/keys; next session)|原文・プロンプト・訳文・Decisions応答を記録（音声・キーを除外。次回から）|원문·프롬프트·번역·Decisions 응답 기록 (음성·키 제외, 다음 세션부터)
验证并使用|Verify and use|確認して使用|확인 후 사용
‹ 返回|‹ Back|‹ 戻る|‹ 뒤로
同传字幕|Live Subtitles|同時字幕|실시간 자막
设置|Settings|設定|설정
字幕窗口|Subtitle window|字幕ウィンドウ|자막 창
听见每一句，轻松翻译与分享|Hear, translate and share every sentence|一言ずつ、翻訳して共有|모든 말을 듣고 번역하고 공유하세요
直播平台|Platform|配信プラットフォーム|방송 플랫폼
声音来源|Audio input|音声入力|오디오 입력
直播间声音|Stream audio|配信音声|방송 오디오
麦克风|Microphone|マイク|마이크
系统默认麦克风|Default microphone|既定のマイク|기본 마이크
刷新麦克风|Refresh devices|マイクを更新|장치 새로 고침
麦克风可直接使用，无需登录。发送聊天才需要账号。|Microphone works without login. Sign in only to send chat.|マイクはログイン不要。チャット送信にはログインが必要です。|마이크는 로그인 없이 사용합니다. 채팅 전송에만 로그인이 필요합니다.
直播间链接|Stream URL|配信URL|방송 URL
自动识别原文语言 → 你想阅读的字幕语言|Detect speech language → Subtitle language|音声言語を自動検出 → 字幕言語|음성 언어 자동 감지 → 자막 언어
日语|Japanese|日本語|일본어
英语|English|英語|영어
中文|Chinese|中国語|중국어
简体中文|Simplified Chinese|簡体字中国語|중국어 간체
繁體中文|Traditional Chinese|繁体字中国語|중국어 번체
韩语|Korean|韓国語|한국어
自动识别|Auto-detect|自動検出|자동 감지
发送方式|Sending|送信方式|전송 방식
自动发送|Auto-send|自動送信|자동 전송
手动发送|Manual-send|手動送信|수동 전송
手动确认|Manual review|手動確認|수동 검토
默认手动审核；开启自动后，每条译文直接发送。|Manual by default. Auto sends each translation directly.|既定は手動確認。自動では各訳文を直接送信します。|기본은 수동 검토입니다. 자동 모드는 번역을 바로 전송합니다.
聊天账号：未登录|Chat account: not signed in|チャット：未ログイン|채팅 계정: 로그인 안 됨
聊天账号：|Chat account: |チャット：|채팅 계정: 
登录 / 导入 Cookie|Sign in / Import cookies|ログイン / Cookie取込|로그인 / 쿠키 가져오기
▶  开始字幕|▶  Start subtitles|▶  字幕を開始|▶  자막 시작
■  停止字幕|■  Stop subtitles|■  字幕を停止|■  자막 중지
开始字幕|Start subtitles|字幕を開始|자막 시작
翻译：还没设置翻译服务|Translation: service not configured|翻訳：サービス未設定|번역: 서비스 설정 필요
翻译：|Translation: |翻訳：|번역: 
实时字幕 / 待处理|Live subtitles / Review|リアルタイム字幕 / 確認待ち|실시간 자막 / 검토
条待处理|pending|件待機中|개 대기 중
当前原文（参考）|Current original (reference)|現在の原文（参考）|현재 원문 (참고)
当前译文 · 可编辑|Current translation · Editable|現在の訳文 · 編集可能|현재 번역 · 편집 가능
跳过|Skip|スキップ|건너뛰기
已跳过|Skipped|スキップ済み|건너뜀
发送到直播间|Send to chat|チャットに送信|채팅으로 전송
发送成功|Sent successfully|送信しました|전송 완료
发送失败|Send failed|送信失敗|전송 실패
等待翻译…|Waiting for translation…|翻訳待ち…|번역 대기 중…
等待识别和翻译…|Waiting for speech and translation…|認識と翻訳を待機中…|음성 인식 및 번역 대기 중…
实时原文：|Live speech: |リアルタイム原文：|실시간 원문: 
等待语音…|Waiting for speech…|音声を待機中…|음성 대기 중…
识别耗时：|ASR time: |認識時間：|인식 시간: 
识别耗时 |ASR time |認識時間 |인식 시간 
（不含直播/分句/翻译等待）|(excluding stream, segmentation and translation wait)|（配信・区切り・翻訳の待ち時間を除く）|(방송·분할·번역 대기 제외)
原文：|Original: |原文：|원문: 
译文：|Translation: |訳文：|번역: 
待发送队列|Upcoming queue|送信待ちキュー|전송 대기열
音频接收 |Audio received |音声受信 |오디오 수신 
声音在本机识别；翻译文字会发给翻译服务。只有你选择发送后，字幕才会发到直播间聊天。|Speech is recognized locally. Text goes to your translation service; chat sends only when requested.|音声はローカルで認識。テキストは翻訳サービスへ送信し、チャットは選択時のみ送信します。|음성은 로컬에서 인식합니다. 텍스트는 번역 서비스로 보내며 채팅은 선택할 때만 전송합니다.
可以开始了|Ready to start|開始できます|시작 준비 완료
还需要设置|Setup needed|設定が必要です|설정 필요
字幕正在运行|Subtitles running|字幕実行中|자막 실행 중
暂时无法继续|Unable to continue|続行できません|계속할 수 없음
字幕已停止|Subtitles stopped|字幕停止中|자막 중지됨
字幕状态|Subtitle status|字幕の状態|자막 상태
准备好了。点下面的按钮开始翻译直播。|Ready. Click Start subtitles below.|準備完了。下のボタンで字幕を開始できます。|준비되었습니다. 아래 자막 시작 버튼을 누르세요.
请先设置翻译服务地址和模型 ID。API Key 按服务要求填写。|Set the translation URL and model ID. Supply an API key if required.|翻訳サービスのURLとモデルIDを設定してください。必要ならAPIキーを入力してください。|번역 서비스 URL과 모델 ID를 설정하세요. 필요하면 API 키를 입력하세요.
字幕已停止，可以重新开始。|Stopped. You can start again.|停止しました。再開できます。|중지되었습니다. 다시 시작할 수 있습니다.
直播连接已结束，可以重新开始。|Stream connection ended. You can restart.|配信接続が終了しました。再開できます。|방송 연결이 종료되었습니다. 다시 시작할 수 있습니다.
正在停止…|Stopping…|停止中…|중지 중…
正在停止字幕…|Stopping subtitles…|字幕を停止中…|자막 중지 중…
正在结束…|Finishing…|終了中…|종료 중…
正在发送…|Sending…|送信中…|전송 중…
正在读取…|Reading…|読込中…|읽는 중…
正在验证登录…|Verifying login…|ログインを確認中…|로그인 확인 중…
正在生成二维码…|Generating QR code…|QRコードを生成中…|QR 코드 생성 중…
正在测试…|Testing…|テスト中…|테스트 중…
正在连接翻译服务…|Connecting to translation service…|翻訳サービスに接続中…|번역 서비스 연결 중…
正在加载语音识别并打开麦克风。就绪后直接说话即可。|Loading ASR and opening microphone. Speak when ready.|音声認識を読み込み、マイクを開いています。準備後に話してください。|음성 인식을 불러오고 마이크를 여는 중입니다. 준비되면 말하세요.
正在连接直播并加载语音识别。保持此窗口打开即可。|Connecting to stream and loading ASR. Keep this window open.|配信に接続し、音声認識を読み込み中です。このウィンドウを開いたままにしてください。|방송 연결 및 음성 인식 로딩 중입니다. 이 창을 열어 두세요.
返回|Back|戻る|뒤로
‹  返回|‹  Back|‹  戻る|‹  뒤로
← 返回|← Back|← 戻る|← 뒤로
翻译服务|Translation service|翻訳サービス|번역 서비스
保存字幕设置|Save subtitle settings|字幕設定を保存|자막 설정 저장
保存设置|Save settings|設定を保存|설정 저장
字幕|Subtitles|字幕|자막
翻译|Translation|翻訳|번역
页面|Layout|レイアウト|레이아웃
记录|Records|記録|기록
关于|About|情報|정보
字幕外观（独立字幕窗口）|Subtitle appearance (overlay)|字幕表示（別ウィンドウ）|자막 모양 (별도 창)
文字大小|Font size|文字サイズ|글자 크기
背景浓淡 / 窗口不透明度（0.1 到 1）|Window opacity (0.1–1)|ウィンドウ不透明度（0.1～1）|창 불투명도 (0.1–1)
保存并预览字幕窗口|Save and preview overlay|保存して字幕をプレビュー|저장 후 자막 미리 보기
显示|Display|表示|표시
同时显示原文（聊天审核原文仍保留）|Show original (review reference always retained)|原文を表示（確認用原文は常に保持）|원문 표시 (검토 원문은 항상 유지)
显示识别和翻译用时|Show ASR and translation timing|認識・翻訳時間を表示|인식 및 번역 시간 표시
字幕大小和保留句数|Subtitle dimensions and retention|字幕サイズと保持数|자막 크기 및 보관 수
字幕宽度 · 屏幕百分比|Width · Screen percentage|幅 · 画面に対する割合|너비 · 화면 비율
字幕高度 · 屏幕百分比|Height · Screen percentage|高さ · 画面に対する割合|높이 · 화면 비율
保留翻译数量（包括待处理；超出时移除最早条目）|Translations to retain (including pending; oldest expire)|翻訳保持数（確認待ちを含む。古いものから削除）|번역 보관 수 (대기 포함, 오래된 항목 삭제)
模式 / 背景与术语|Mode / Background and glossary|モード / 背景・用語|모드 / 배경 및 용어
主播模式|Streamer mode|配信者モード|스트리머 모드
对话模式|Conversation mode|会話モード|대화 모드
编辑背景和术语表|Edit background and glossary|背景・用語集を編集|배경 및 용어집 편집
结合上下文翻译|Translation context|文脈を利用した翻訳|문맥 번역
参考之前已完成的原文和译文|Use previous finalized originals and translations|確定済みの原文と訳文を参照|이전 확정 원문 및 번역 참조
参考前面几句（越多可能越慢）|Previous sentences (more may be slower)|参照する文の数（多いほど遅くなる場合があります）|이전 문장 수 (많으면 느려질 수 있음)
字幕怎么出现|Subtitle updates|字幕の更新方式|자막 표시 방식
边听边出|Live drafts|逐次表示|실시간 초안
说完再出|Final sentences only|発話終了後に表示|완료된 문장만 표시
去掉同一条识别结果内重复的字句（也可能去掉真实重复）|Remove repeated phrases (may remove intended repetitions)|認識結果内の繰り返しを削除（意図した反復も削除される場合があります）|반복 문구 제거 (의도한 반복도 제거될 수 있음)
在线 Decisions 模型辅助（可选）|Online Decisions assistance (optional)|オンラインDecisions補助（任意）|온라인 Decisions 지원 (선택)
智能断句 · 暂停时判断是否说完，最多额外等待约 1 秒|Smart segmentation · Up to 1s extra pause wait|スマート区切り · 最大約1秒追加待機|스마트 문장 분할 · 최대 약 1초 추가 대기
检查译文 · 有问题时重译一次，可能增加延迟|Check translation · One retry if flagged; may add delay|訳文を確認 · 問題があれば1回再翻訳（遅延する場合があります）|번역 검토 · 문제 시 한 번 재번역, 지연될 수 있음
自定义|Custom|カスタム|사용자 지정
自定义服务完整地址（System One / Decisions）|Custom endpoint (System One / Decisions)|カスタムURL（System One / Decisions）|사용자 지정 URL (System One / Decisions)
自定义模型|Custom model|カスタムモデル|사용자 지정 모델
Decisions API Key（已有密钥留空保留）|Decisions API key (blank keeps existing)|Decisions APIキー（空欄で既存キーを保持）|Decisions API 키 (빈칸은 기존 키 유지)
清除 Decisions Key|Clear Decisions key|Decisionsキーを削除|Decisions 키 삭제
OpenCode Zen（免费，不用 key）|OpenCode Zen (free, no key)|OpenCode Zen（無料・キー不要）|OpenCode Zen (무료, 키 불필요)
TypeSafe 官方|TypeSafe official|TypeSafe公式|TypeSafe 공식
黑白|Black and white|モノクロ|흑백
经典白|Classic white|クラシックホワイト|클래식 화이트
影院黄|Cinema yellow|シネマイエロー|시네마 옐로
薄荷绿|Mint green|ミントグリーン|민트 그린
天空蓝|Sky blue|スカイブルー|스카이 블루
樱花粉|Sakura pink|桜ピンク|사쿠라 핑크
白底黑字|Black on white|白地に黒文字|흰 배경에 검은 글자
字幕文本 / 使用记录|Subtitle text / Session records|字幕テキスト / 使用記録|자막 텍스트 / 사용 기록
保存最终字幕文本（原文 + 译文）|Save finalized subtitle text (original + translation)|確定字幕を保存（原文＋訳文）|확정 자막 저장 (원문 + 번역)
保存诊断会话日志（提示词、请求和时间）|Save diagnostics (prompts, requests and timing)|診断ログを保存（プロンプト・要求・時間）|진단 로그 저장 (프롬프트·요청·시간)
打开本地记录文件夹|Open records folder|記録フォルダーを開く|로컬 기록 폴더 열기
已发送字幕 → 剪辑导出|Sent subtitles → Editing export|送信済み字幕 → 編集用出力|전송된 자막 → 편집 내보내기
录像开始时间（本机时区，完整日期；也支持 ISO 时区）|Recording start (full local date/time; ISO zone accepted)|録画開始（完全な日時。ISOタイムゾーン対応）|녹화 시작 (전체 날짜·시간, ISO 시간대 지원)
录像从现在开始|Recording starts now|録画開始を現在時刻に設定|녹화 시작을 현재 시간으로 설정
导出已发送 SRT + CSV|Export sent SRT + CSV|送信済みSRT＋CSVを出力|전송된 SRT + CSV 내보내기
背景说明|Background description|背景説明|배경 설명
术语表（每行一个，例如 原词: 译法）|Glossary (one per line: term: translation)|用語集（1行1項目：原語: 訳語）|용어집 (한 줄에 하나: 원어: 번역)
应用（再点保存字幕设置）|Apply (then save subtitle settings)|適用（その後、字幕設定を保存）|적용 (이후 자막 설정 저장)
服务地址（OpenAI 兼容）|Service URL (OpenAI-compatible)|サービスURL（OpenAI互換）|서비스 URL (OpenAI 호환)
模型 ID|Model ID|モデルID|모델 ID
API Key 可选；无 Key 的服务可以留空。|API key is optional for keyless services.|キー不要のサービスではAPIキーは空欄にできます。|키가 필요 없는 서비스에서는 API 키를 비워둘 수 있습니다.
已有密钥已保存；留空会继续使用。|A key is saved; blank keeps it.|キーは保存済み。空欄で保持します。|저장된 키가 있습니다. 빈칸은 기존 키를 유지합니다.
显示 Key|Show key|キーを表示|키 표시
隐藏 Key|Hide key|キーを隠す|키 숨기기
清除已保存的 Key|Clear saved key|保存済みキーを削除|저장된 키 삭제
测试连接|Test connection|接続をテスト|연결 테스트
设置已保存。|Settings saved.|設定を保存しました。|설정을 저장했습니다.
字幕设置已保存|Subtitle settings saved|字幕設定を保存しました|자막 설정 저장됨
外观立即生效；内容、断句、译文检查和记录开关从下次开始字幕生效。|Appearance applies now; processing and logging apply next session.|外観は即時反映。内容・区切り・確認・記録は次回セッションから反映します。|모양은 즉시 적용됩니다. 처리 및 기록 설정은 다음 세션부터 적용됩니다.
没有记录|No records|記録なし|기록 없음
导出失败|Export failed|出力失敗|내보내기 실패
无法打开记录|Cannot open records|記録を開けません|기록을 열 수 없음
无法保存|Cannot save|保存できません|저장할 수 없음
无法保存字幕设置|Cannot save subtitle settings|字幕設定を保存できません|자막 설정을 저장할 수 없음
无法清除|Cannot clear|削除できません|삭제할 수 없음
需要登录|Sign-in required|ログインが必要です|로그인 필요
需要直播间地址|Stream URL required|配信URLが必要です|방송 URL 필요
确认自动发送|Confirm auto-send|自動送信を確認|자동 전송 확인
每条完成的翻译都会直接发送到直播间聊天。确定继续吗？|Each finalized translation will be sent directly to chat. Continue?|確定した訳文をチャットに直接送信します。続行しますか？|확정 번역이 채팅으로 바로 전송됩니다. 계속하시겠습니까?
发送翻译弹幕前，需要先登录当前直播平台。Cookie 只会保存在本次运行中。|Sign in to this platform before sending. Cookies stay in memory only.|送信前にプラットフォームへログインしてください。Cookieはメモリ内のみ保持します。|전송 전에 플랫폼에 로그인하세요. 쿠키는 메모리에만 보관됩니다.
收听直播或发送弹幕时，请填写直播间链接。|Enter the stream URL to listen or send chat.|配信の視聴・チャット送信には配信URLを入力してください。|방송을 듣거나 채팅을 보내려면 방송 URL을 입력하세요.
直播间地址不正确|Invalid stream URL|配信URLが不正です|잘못된 방송 URL
未登录发送账号；可编辑或跳过，登录后重新开始字幕即可发送。|Not signed in. Edit or skip locally; sign in and restart to send.|未ログインです。編集・スキップは可能。ログイン後、字幕を再開すると送信できます。|로그인되지 않았습니다. 편집·건너뛰기는 가능하며 로그인 후 다시 시작하면 전송할 수 있습니다.
请输入要发送的文字，或点击「跳过」。|Enter text to send, or click Skip.|送信する文字を入力するか、スキップしてください。|전송할 텍스트를 입력하거나 건너뛰기를 누르세요.
发送失败，请检查登录状态和直播间权限。|Send failed. Check login and room permissions.|送信失敗。ログインと配信の権限を確認してください。|전송 실패. 로그인 및 방송 권한을 확인하세요.
发送记录未保存|Send record not saved|送信記録を保存できませんでした|전송 기록 저장 실패
消息已发送，但本地记录保存失败；不要再次发送，请检查磁盘空间。|Sent, but record saving failed. Do not resend; check disk space.|送信済みですが記録保存に失敗。再送せず、空き容量を確認してください。|전송되었지만 기록 저장 실패. 재전송하지 말고 디스크 공간을 확인하세요.
已发送，但本地记录未保存|Sent, but local record not saved|送信済み。ローカル記録は未保存|전송됨, 로컬 기록 미저장
无法读取麦克风|Cannot read microphone|マイクを読み取れません|마이크를 읽을 수 없음
没有麦克风|No microphone|マイクなし|마이크 없음
无法读取录音设备，请检查设备连接和麦克风权限。|Check recording device connection and microphone permissions.|録音機器の接続とマイク権限を確認してください。|녹음 장치 연결과 마이크 권한을 확인하세요.
没有找到录音设备，请连接麦克风后刷新。|No recording device found. Connect a microphone and refresh.|録音機器がありません。マイクを接続して更新してください。|녹음 장치가 없습니다. 마이크를 연결하고 새로 고침하세요.
连接直播间失败，请确认直播正在播放，然后再试一次。|Stream connection failed. Check that it is live and retry.|配信接続に失敗。配信中であることを確認して再試行してください。|방송 연결 실패. 방송 중인지 확인하고 다시 시도하세요.
翻译服务无法访问，请打开「设置」检查 API Key 和服务地址。|Cannot access translation service. Check API key and URL in Settings.|翻訳サービスにアクセスできません。設定でキーとURLを確認してください。|번역 서비스에 접근할 수 없습니다. 설정에서 API 키와 URL을 확인하세요.
翻译服务暂时限流，请稍后再试或检查账户额度。|Translation service rate-limited. Retry later or check quota.|翻訳サービスの利用制限中です。後で再試行するか残高を確認してください。|번역 서비스 요청 제한. 나중에 다시 시도하거나 할당량을 확인하세요.
请先点「设置」，填写翻译服务地址和模型 ID。API Key 按服务要求填写。|Open Settings and enter the service URL and model ID; key if required.|設定でサービスURLとモデルIDを入力してください。必要ならキーも入力してください。|설정에서 서비스 URL과 모델 ID를 입력하세요. 필요하면 키도 입력하세요.
登录|Sign in|ログイン|로그인
聊天账号|Chat account|チャットアカウント|채팅 계정
连接 |Connect |接続 |연결 
粘贴 Cookie|Paste cookies|Cookieを貼り付け|쿠키 붙여넣기
从 Firefox 读取|Read from Firefox|Firefoxから読み込む|Firefox에서 읽기
验证并登录|Verify and sign in|確認してログイン|확인 후 로그인
取消|Cancel|キャンセル|취소
关闭|Close|閉じる|닫기
哔哩哔哩扫码登录|哔哩哔哩 QR sign-in|哔哩哔哩 QRログイン|哔哩哔哩 QR 로그인
请用 Bilibili 手机客户端扫码。|Scan with the Bilibili mobile app.|Bilibiliアプリで読み取ってください。|Bilibili 모바일 앱으로 스캔하세요.
已扫码，请在手机上确认登录。|Scanned. Confirm on your phone.|読取済み。スマートフォンでログインを確認してください。|스캔됨. 휴대폰에서 로그인을 확인하세요.
二维码已过期，请关闭窗口后重新扫码。|QR expired. Close and generate a new code.|QRの期限切れ。閉じて再生成してください。|QR 만료. 창을 닫고 새 코드를 생성하세요.
扫码登录失败，请关闭此窗口重试或使用 Cookie 登录。|QR sign-in failed. Retry or use cookies.|QRログイン失敗。再試行またはCookieをご利用ください。|QR 로그인 실패. 다시 시도하거나 쿠키를 사용하세요.
请稍候，正在读取 Firefox Cookie 并验证登录…|Reading Firefox cookies and verifying login…|FirefoxのCookieを読み込み、ログイン確認中…|Firefox 쿠키를 읽고 로그인 확인 중…
请先粘贴 Cookie 内容。|Paste cookies first.|先にCookieを貼り付けてください。|먼저 쿠키를 붙여넣으세요.
已登录；Cookie 仅保存在内存中|Signed in; cookies stay in memory only|ログイン済み。Cookieはメモリ内のみ保持|로그인됨. 쿠키는 메모리에만 보관
语言|Language|言語|언어
深色|Dark|ダーク|다크
浅色|Light|ライト|라이트
界面设置未保存|Interface preferences not saved|画面設定を保存できませんでした|인터페이스 설정 저장 실패
无法保存界面设置，请检查文件权限和磁盘空间。|Cannot save interface preferences. Check file permissions and disk space.|画面設定を保存できません。権限と空き容量を確認してください。|인터페이스 설정을 저장할 수 없습니다. 파일 권한과 디스크 공간을 확인하세요.
界面设置加载失败|Interface preferences could not be loaded|画面設定を読み込めませんでした|인터페이스 설정 로딩 실패
界面设置损坏或无法读取；本次使用系统语言和浅色主题。|Interface preferences are unreadable; using system language and light theme.|画面設定が読めません。システム言語とライトテーマを使用します。|인터페이스 설정을 읽을 수 없어 시스템 언어와 라이트 테마를 사용합니다.
界面设置或 env 默认值无效；本次使用系统语言和浅色主题，请检查配置。|Invalid interface settings or env defaults; using system language and light theme. Check configuration.|画面設定または env の初期値が無効です。システム言語とライトテーマを使用します。設定を確認してください。|인터페이스 설정 또는 env 기본값이 잘못되었습니다. 시스템 언어와 라이트 테마를 사용합니다. 설정을 확인하세요.
字幕设置或 env 默认值无效；本次使用默认设置，请检查配置后重新保存。|Invalid subtitle settings or env defaults; using built-in defaults. Check configuration before saving.|字幕設定または env の初期値が無効です。既定値を使用します。設定を確認してから保存してください。|자막 설정 또는 env 기본값이 잘못되었습니다. 기본 설정을 사용합니다. 설정을 확인한 후 저장하세요.
悬浮窗位置设置无效|Invalid floating window position|フローティングウィンドウの位置が無効です|플로팅 창 위치가 잘못되었습니다
请将 OVERLAY_X 和 OVERLAY_Y 同时设为整数；本次使用默认位置。|Set both OVERLAY_X and OVERLAY_Y to integers; using the default position.|OVERLAY_X と OVERLAY_Y を両方整数に設定してください。既定の位置を使用します。|OVERLAY_X와 OVERLAY_Y를 모두 정수로 설정하세요. 기본 위치를 사용합니다.
已按保留数量移除 |Removed oldest |保持数に従い古い翻訳を |보관 수에 따라 오래된 번역 
 条最早待处理翻译。| pending translations.| 件削除しました。|개를 삭제했습니다.
与程序的连接中断，正在重新连接…|Lost connection to the app. Reconnecting…|アプリとの接続が切れました。再接続しています…|앱과의 연결이 끊어졌습니다. 다시 연결하는 중…
请关闭此页面，解决问题后重新打开程序。|Please close this page, fix the problem and reopen the app.|このページを閉じ、問題を解決してからアプリを開き直してください。|이 페이지를 닫고 문제를 해결한 뒤 앱을 다시 여세요.
粘贴直播间链接，会自动识别平台|Paste a live room link; the platform is detected automatically|ライブ配信のリンクを貼り付けると、プラットフォームを自動で判別します|라이브 링크를 붙여넣으면 플랫폼을 자동으로 인식합니다
原文语言|Source language|原文の言語|원문 언어
在 OBS 中添加「浏览器」来源，粘贴下面的网址，即可显示大字幕。也可以直接在浏览器中打开。|In OBS add a "Browser" source and paste the address below to show large subtitles. You can also open it in a browser.|OBSで「ブラウザ」ソースを追加し、下のアドレスを貼り付けると大きな字幕を表示できます。ブラウザで直接開くこともできます。|OBS에서 '브라우저' 소스를 추가하고 아래 주소를 붙여넣으면 큰 자막이 표시됩니다. 브라우저에서 바로 열 수도 있습니다.
复制网址|Copy address|アドレスをコピー|주소 복사
打开预览|Open preview|プレビューを開く|미리보기 열기
字幕会显示在这里。|Subtitles will appear here.|字幕はここに表示されます。|자막이 여기에 표시됩니다.
退出程序|Quit app|アプリを終了|앱 종료
字幕外观|Subtitle look|字幕の見た目|자막 모양
配色|Colors|配色|색상
选择字幕会话|Choose a subtitle session|字幕セッションを選択|자막 세션 선택
好的|OK|OK|확인
退出后字幕会停止，登录状态也会清除。确定退出吗？|Quitting stops subtitles and clears logins. Quit now?|終了すると字幕が止まり、ログイン状態も消去されます。終了しますか？|종료하면 자막이 멈추고 로그인 상태도 지워집니다. 종료할까요?
程序已退出|The app has quit|アプリを終了しました|앱이 종료되었습니다
现在可以关闭此页面。要再次使用，请重新双击「Start Translation.bat」。|You can close this page now. To use it again, double-click "Start Translation.bat".|このページを閉じて構いません。再度使うには「Start Translation.bat」をダブルクリックしてください。|이제 이 페이지를 닫아도 됩니다. 다시 쓰려면 "Start Translation.bat"을 더블클릭하세요.
连接中断|Connection lost|接続が切れました|연결 끊김
出错了|Something went wrong|エラーが発生しました|문제가 발생했습니다
发生了意外错误，请重试。|An unexpected error occurred. Please try again.|予期しないエラーが発生しました。もう一度お試しください。|예기치 않은 오류가 발생했습니다. 다시 시도하세요.
继续|Continue|続行|계속
识别耗时|Recognition time|認識時間|인식 시간
已复制网址|Address copied|アドレスをコピーしました|주소를 복사했습니다
连接失败：|Connection failed: |接続に失敗しました：|연결 실패: 
保存位置：|Saved to: |保存先：|저장 위치: 
已应用，请再点「保存字幕设置」。|Applied. Now click "Save subtitle settings".|適用しました。「字幕設定を保存」を押してください。|적용했습니다. '자막 설정 저장'을 누르세요.
隐藏|Hide|隠す|숨기기
哔哩哔哩|哔哩哔哩|哔哩哔哩|哔哩哔哩
猫耳FM|猫耳FM|猫耳FM|猫耳FM
连接 哔哩哔哩 聊天账号|Connect 哔哩哔哩 chat account|哔哩哔哩チャットアカウントを接続|哔哩哔哩 채팅 계정 연결
连接 猫耳FM 聊天账号|Connect 猫耳FM chat account|猫耳FMチャットアカウントを接続|猫耳FM 채팅 계정 연결
请使用哔哩哔哩手机 App 扫码，并在手机上确认登录。|Scan with the 哔哩哔哩 app and confirm sign-in on your phone.|哔哩哔哩アプリでスキャンし、スマートフォンでログインを確認してください。|哔哩哔哩 앱으로 스캔한 후 휴대폰에서 로그인을 확인하세요.
请输入有效的哔哩哔哩直播间链接或房间号。|Enter a valid 哔哩哔哩 live URL or room ID.|有効な哔哩哔哩配信URLまたは部屋IDを入力してください。|올바른 哔哩哔哩 방송 URL 또는 방 ID를 입력하세요.
不支持此直播间地址；请选择哔哩哔哩、YouTube 或猫耳FM的直播链接。|Unsupported URL. Use a 哔哩哔哩, YouTube or 猫耳FM live link.|未対応のURLです。哔哩哔哩・YouTube・猫耳FMの配信リンクを使用してください。|지원하지 않는 URL입니다. 哔哩哔哩, YouTube 또는 猫耳FM 방송 링크를 사용하세요.
请输入猫耳FM直播间链接或数字房间号。|Enter a 猫耳FM live URL or numeric room ID.|猫耳FM配信URLまたは数字の部屋IDを入力してください。|猫耳FM 방송 URL 또는 숫자 방 ID를 입력하세요.
"""


TRANSLATIONS = {}
for _row in _ROWS.strip().splitlines():
    _source, _en, _ja, _ko = _row.split("|")
    TRANSLATIONS[_source] = {"en": _en, "ja": _ja, "ko": _ko}

TRANSLATIONS.update({
    "服务地址示例：https://api.openai.com/v1\nAPI Key 只保存在这台电脑的配置文件中，不会发送给直播间。": {
        "en": "Example URL: https://api.openai.com/v1\nAPI keys are stored only in this computer's configuration, never sent to chat.",
        "ja": "URL例：https://api.openai.com/v1\nAPIキーはこのPCの設定にのみ保存し、チャットには送りません。",
        "ko": "URL 예: https://api.openai.com/v1\nAPI 키는 이 컴퓨터의 설정에만 저장하며 채팅으로 보내지 않습니다.",
    },
    "本机语音识别 · 自选翻译服务 · 哔哩哔哩 / YouTube / 猫耳FM聊天\n借鉴 Simul Subtitle 的使用方式，Python 实现。\n接收时间不是源网站的直播时间码：直播缓冲/网络延迟仍需在剪辑软件中校正。SRT 不包含样式。": {
        "en": "Local speech recognition · Your translation service · 哔哩哔哩 / YouTube / 猫耳FM chat\nPython implementation inspired by Simul Subtitle.\nReceipt clocks are not broadcast timecodes. Correct buffering/network offsets in your editor. SRT has no styling.",
        "ja": "ローカル音声認識 · 任意の翻訳サービス · 哔哩哔哩 / YouTube / 猫耳FMチャット\nSimul Subtitleを参考にしたPython実装。\n受信時刻は配信タイムコードではありません。バッファや通信遅延は編集で補正してください。SRTに装飾は含みません。",
        "ko": "로컬 음성 인식 · 선택한 번역 서비스 · 哔哩哔哩 / YouTube / 猫耳FM 채팅\nSimul Subtitle을 참고한 Python 구현.\n수신 시간은 방송 타임코드가 아닙니다. 버퍼링·네트워크 지연은 편집기에서 보정하세요. SRT에는 스타일이 없습니다.",
    },
})
