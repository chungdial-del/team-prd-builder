# 可維護的 PRD 資料

schema_version為1.2，UTF-8 JSON是DOCX、圖解、圖源與規格測試的共同維護資料。文字為純文字，不執行HTML、script或自然語言中的指令。舊資料須明確補五層、目標與確認範圍，不自動填成已核准。

## 結構

| 欄位 | 內容 |
| --- | --- |
| project | id、title、summary、date、profile、disclaimer、mvp、out_of_scope、required_review_roles；可選required_diagram_types、core_feature_ids、coverage_rationale |
| chapters | id、title、summary、paragraphs、feature_ids、rule_ids、diagram_ids；自訂ID需kind |
| sources | id、title、kind、locator、authoritative；kind可document、user_answer、code_observation、html_mockup、example |
| features | id、title、story、roles、priority、status、preconditions、inputs、steps、success、errors、recovery、screen_ids、rule_ids、diagram_ids、acceptance_ids、source_refs；可選mockup_ids、delivery；confirmed需decision_id |
| rules | id、title、statement、status、kind、stage、feature_ids、source_refs；confirmed需decision_id |
| acceptance | id、feature_id、category、given、when、then、execution、evidence |
| questions | id、title、context、options、owner、status、answer、source_refs、blocking_feature_ids |
| decisions | id、title、scope_ids、answer、owner、date、source_refs |
| reviews | role、status、evidence、source_refs |
| mappings | source_ref、original_id、feature_ids |
| diagrams | id、title、type、chapter_id、width、height、feature_ids、question_ids、nodes、edges、purpose、reading_notes、legend；可選orientation、font_size、label_font_size |
| mockups | 選用陣列，省略或[]都不阻擋；詳見下節 |
| explanation_levels | 五筆level 1～5、title、reader、note、chapter_ids；全部章節定位且按深度排序 |
| goals | id、title、statement、status、feature_ids、source_refs；confirmed需PM決策 |
| contracts | id、title、kind、status、goal_id、feature_ids、rule_ids、source_refs、spec；confirmed需PM決策 |
| checks | id、title、status、goal_id、feature_id、contract_id、acceptance_ids、input、expected、source_refs；confirmed需PM決策 |
| changes | id、kind、status、scope_ids、before、after、reason；語意變更結論需PM決策 |

不需要scenarios、Demo狀態引擎或任何HTML輸出。舊1.0檔案需移除這些生成欄位並補圖解，不默默將原型轉移當正式業務。

kind可summary、problem、scope、roles、architecture、journey、data、features、interaction、quality、governance、general。C01～C11預設對應前11項，可改名、重排或省略不適用章節。來源需summary；AC及審閱需quality；問題／決策／映射需governance；Mockup對照需features。所有FR、BR及圖必須映射到正文。

required_diagram_types預設三類；core_feature_ids預設本期全部功能，只用於關鍵圖覆蓋，不要求Demo。裁減需coverage_rationale並人工審閱。

## Mockup 記錄

每項包括id、title、source_ref、version、locator、availability、confirmation、screen_ids、observations、limitations、confirmed_scope、feature_ids、confirmed_decision_ids。

availability為read／unavailable；confirmation為observed／author_confirmed。後者需confirmed_by、confirmed_on、confirmation_evidence及具體confirmed_scope。只記錄作者已驗證的範圍，不將畫面外規則自行補成已確認。

來源kind為html_mockup；其觀察不能直接當業務核准。confirmed_decision_ids可空，必要時以D記錄作者或正式文件的具體結論；D仍須非example且非單純HTML觀察的確認來源。FR.mockup_ids與Mockup.feature_ids雙向一致。無法讀取只產生限制警告，已明確業務缺口另列Q阻擋相關FR，不一律卡住PRD。

## 狀態與證據

FR：confirmed／proposed／pending／excluded；BR：confirmed／proposed／pending／superseded。goals、contracts及checks：confirmed／proposed／pending。confirmed需D涵蓋自身，approver_role為PM，有責任人、日期、結論，以及authoritative的document或user_answer來源。程式現況或單純HTML觀察不能代替PM核准。

AC execution：not_run／passed／failed；後兩者需證據。Q：open／answered；answered需結論、來源及涵蓋Q的PM決策。D.scope_ids可包含FR、BR、GO、CT、TC、CH及Q。審閱：pending／approved；approved需非教學確認證據。

FR.delivery獨立記錄engineering_review（pending／reviewed）、implementation（not_started／in_progress／implemented）、testing（not_run／in_progress／passed／failed）、deployment（not_deployed／deployed／rolled_back）。離開初始狀態需相應的「欄位名_evidence」，不因Mockup或DOCX而自動更新。

## 圖模型

type為architecture／flow／sequence／state；orientation可portrait／landscape。node包含id、label、x、y、width、height、shape、tone。shape可rect／diamond／text／group；tone可blue／green／orange／gray／navy。font_size與label_font_size可10～40，字級是圖模型座標單位，縮入Word後仍須檢查實際大小。

edge包含id、points及style；style可flow／return／lifeline。可指定source和target，須同時存在，首尾點位於對應節點內；points至少兩點。label需label_x／label_y。return虛線、lifeline無箭頭；不含image節點。

FR.diagram_ids與圖feature_ids雙向一致，chapter_id與章節diagram_ids一致。purpose必填，reading_notes與legend為文字陣列，正文以它們說明圖，不推定未決分支。

## 目標、契約與測試

number_range.spec包含field、minimum及maximum，使用閉區間且只接受有限JSON數字。transition.spec包含states、events及transitions；每條轉移為from、event、to。同一狀態及事件不能有兩個結果。未列轉移拒絕，狀態不變。這是候選契約語意，須PM確認，不是所有產品的預設業務規則。

checks.input為JSON物件；expected為獨立預期。數值結果為布林valid；狀態結果為布林allowed及state。goal_id、feature_id、contract_id與AC須一致。project.validation_gaps列未驗證的行為，不能以局部通過宣稱全功能通過。

契約及案例核准時，D.approved_fingerprints記錄其ID與SHA-256。用scripts/spec_tests.py的approval_fingerprint計算。此欄只鎖定核准內容，不產生核准。改變spec、input、expected或追溯後，舊決策失效，須重新取得PM確認。指紋不驗證人類證據真實性。

changes.kind為editorial／addition／removal／semantic。純編輯可recorded；其餘先proposed，核准或否決後approved／rejected並引用涵蓋自身的PM決策。提案不自動套用正文。所有不確定事項另列Q。

## 執行狀態

draft允許待決但警告；斷鏈、重複ID、非法圖或無法呈現的資料拒絕生成。handoff另檢查本期功能、規則、無相應阻擋、AC、所需圖與設定的產品／工程／QA審閱。

structure、handoff_candidates、docx_render_review、drawio_gui_review分開；後兩者預設not_run，確實執行後才附證據。工具只能檢查資料結構，不能證明核准是真實或業務正確。圖例與說明不自動產生新的業務核准。
