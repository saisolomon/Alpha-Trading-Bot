//+------------------------------------------------------------------+
//| BotOrchestrator.mq5                                              |
//| Self-healing supervisor for the FTMO bot portfolio.              |
//|                                                                  |
//| Reads MQL5/Files/bot_manifest.txt (one EA name per line) and    |
//| ensures each listed EA stays attached to a D1 chart for its     |
//| primary symbol. If an EA goes missing (user removed, MT5 crash, |
//| chart closed), the orchestrator re-deploys it within ~60s.      |
//|                                                                  |
//| Symbol derivation uses the asset-first naming convention         |
//| documented in CLAUDE.md §8: the first underscore-delimited       |
//| token of the EA filename is the primary chart symbol.            |
//|   US500_MeanRev         → opens US500 D1 chart                   |
//|   XAUUSD_XAGUSD_Pairs   → opens XAUUSD D1 chart                  |
//|   AUDJPY_CHFJPY_Carry   → opens AUDJPY D1 chart                  |
//|   USDMXN_USDZAR_Carry   → opens USDMXN D1 chart                  |
//|                                                                  |
//| Templates: this EA uses ChartApplyTemplate to attach each child  |
//| EA. It AUTO-SAVES a template the first time it observes the EA   |
//| attached anywhere (so the user's one-time manual attach + that   |
//| save become permanent). Templates live at                        |
//| MQL5/Profiles/Templates/<EAname>.tpl.                            |
//|                                                                  |
//| Setup (one-time per fresh MT5 install):                          |
//|   1. Attach this EA to any chart (it doesn't matter which).      |
//|      It will start scanning every 60s.                           |
//|   2. The first time you have each child EA attached anywhere,    |
//|      this orchestrator saves a template for it automatically.    |
//|   3. After that, removing a child EA → orchestrator re-attaches  |
//|      it within 60s.                                              |
//|                                                                  |
//| Future EAs: I append to bot_manifest.txt as part of my deploy    |
//| script. Orchestrator picks up the new entry within 60s. No GUI   |
//| work required from you for default-input EAs.                    |
//+------------------------------------------------------------------+
#property copyright "FTMO bot"
#property version   "0.10"
#property strict

input string  InpManifestFile      = "bot_manifest.txt";  // in MQL5/Files/
input int     InpPollSeconds       = 60;
input ENUM_TIMEFRAMES InpChartPeriod = PERIOD_D1;
input bool    InpVerbose           = true;     // log every poll cycle (turn off after burn-in)
input bool    InpAutoSaveTemplates = true;     // auto-save .tpl on first sighting
//-- Broker-specific symbol suffix. Some brokers append a suffix to
//-- every symbol (e.g. OANDA Simulation Trading appends ".sim", some
//-- ECNs append "_" or ".pro"). The orchestrator appends this when
//-- deriving the chart symbol from the EA name. Leave empty for
//-- brokers with plain symbol names.
input string  InpSymbolSuffix      = ".sim";   // OANDA-Demo-1 uses .sim

//+------------------------------------------------------------------+
//| State                                                            |
//+------------------------------------------------------------------+
string g_manifest[];     // EA names from manifest
int    g_poll_count = 0;
datetime g_last_manifest_check = 0;

//+------------------------------------------------------------------+
//| Derive primary chart symbol from EA filename                      |
//|   "AUDJPY_CHFJPY_Carry" -> "AUDJPY"                              |
//|   "US500_MeanRev"        -> "US500"                              |
//|                                                                  |
//| Returns empty string if the name doesn't fit the convention.     |
//+------------------------------------------------------------------+
string PrimarySymbolFromEAName(const string ea_name) {
   int underscore = StringFind(ea_name, "_");
   if(underscore <= 0) return "";
   string base = StringSubstr(ea_name, 0, underscore);
   // Append broker-specific suffix (e.g. ".sim" for OANDA Simulation
   // Trading). Empty suffix = plain symbol names (e.g. MetaQuotes).
   return base + InpSymbolSuffix;
}

//+------------------------------------------------------------------+
//| Read manifest from MQL5/Files/<InpManifestFile> into g_manifest. |
//| One EA name per line; lines starting with # are comments.        |
//+------------------------------------------------------------------+
bool LoadManifest() {
   int h = FileOpen(InpManifestFile, FILE_READ|FILE_TXT|FILE_ANSI);
   if(h == INVALID_HANDLE) {
      PrintFormat("[BotOrchestrator] manifest %s not found (err=%d) -- create it in MQL5/Files/",
                  InpManifestFile, GetLastError());
      return false;
   }
   ArrayResize(g_manifest, 0);
   while(!FileIsEnding(h)) {
      string line = FileReadString(h);
      StringTrimLeft(line); StringTrimRight(line);
      if(StringLen(line) == 0) continue;
      if(StringGetCharacter(line, 0) == '#') continue;
      int n = ArraySize(g_manifest);
      ArrayResize(g_manifest, n + 1);
      g_manifest[n] = line;
   }
   FileClose(h);
   return true;
}

//+------------------------------------------------------------------+
//| Search all open charts for one running the named EA.             |
//| Returns the chart_id, or -1 if not found.                        |
//+------------------------------------------------------------------+
long FindChartRunningEA(const string ea_name) {
   long chart = ChartFirst();
   while(chart >= 0) {
      string attached = ChartGetString(chart, CHART_EXPERT_NAME);
      if(attached == ea_name) return chart;
      chart = ChartNext(chart);
   }
   return -1;
}

//+------------------------------------------------------------------+
//| Search open charts for one already showing the given symbol +    |
//| timeframe. Returns chart_id, or -1 if none.                      |
//+------------------------------------------------------------------+
long FindChartFor(const string symbol, const ENUM_TIMEFRAMES tf) {
   long chart = ChartFirst();
   while(chart >= 0) {
      if(ChartSymbol(chart) == symbol && ChartPeriod(chart) == tf) return chart;
      chart = ChartNext(chart);
   }
   return -1;
}

//+------------------------------------------------------------------+
//| Save the named EA's template if not already present, by reading  |
//| from its currently-running chart. This is how we auto-learn      |
//| template content -- user attaches once, we capture it.           |
//+------------------------------------------------------------------+
void AutoSaveTemplateIfNew(const string ea_name) {
   if(!InpAutoSaveTemplates) return;
   string tpl_name = ea_name + ".tpl";
   // Check if template already exists by trying to open it
   int probe = FileOpen("..\\Profiles\\Templates\\" + tpl_name,
                         FILE_READ|FILE_BIN|FILE_COMMON);
   if(probe != INVALID_HANDLE) {
      FileClose(probe);
      return;  // template already exists, nothing to do
   }
   // Find a chart running this EA, save template from it
   long chart = FindChartRunningEA(ea_name);
   if(chart < 0) return;  // not currently running anywhere -> can't save
   if(ChartSaveTemplate(chart, tpl_name)) {
      PrintFormat("[BotOrchestrator] auto-saved template %s from chart %I64d",
                  tpl_name, chart);
   } else {
      PrintFormat("[BotOrchestrator] ChartSaveTemplate(%s) failed err=%d",
                  tpl_name, GetLastError());
   }
}

//+------------------------------------------------------------------+
//| Deploy one manifest entry: ensure a chart exists for its primary |
//| symbol, attach the EA via template if not already running.       |
//| Returns status code for logging.                                 |
//+------------------------------------------------------------------+
string DeployEA(const string ea_name) {
   // 1) Already running somewhere? Just record + maybe save template.
   long existing = FindChartRunningEA(ea_name);
   if(existing >= 0) {
      AutoSaveTemplateIfNew(ea_name);
      return "ok (running on chart " + IntegerToString(existing) + ")";
   }
   // 2) Derive symbol from name
   string symbol = PrimarySymbolFromEAName(ea_name);
   if(StringLen(symbol) == 0) {
      return "FAIL: cannot derive symbol from name (not asset-first-formatted)";
   }
   if(!SymbolSelect(symbol, true)) {
      return "FAIL: SymbolSelect(" + symbol + ") returned false (symbol not on broker?)";
   }
   // 3) Find or create a D1 chart for the symbol
   long chart = FindChartFor(symbol, InpChartPeriod);
   if(chart < 0) {
      chart = ChartOpen(symbol, InpChartPeriod);
      if(chart == 0) {
         return "FAIL: ChartOpen(" + symbol + ") returned 0 (err=" +
                 IntegerToString(GetLastError()) + ")";
      }
   }
   // 4) Apply template -- this is the only way to attach an EA programmatically.
   //    Template lives at MQL5/Profiles/Templates/<ea_name>.tpl
   string tpl = ea_name + ".tpl";
   if(!ChartApplyTemplate(chart, tpl)) {
      int err = GetLastError();
      return "FAIL: ChartApplyTemplate(" + tpl + ") err=" + IntegerToString(err) +
             " (save the template via right-click on a chart with " + ea_name + " attached)";
   }
   return "deployed " + ea_name + " to " + symbol + " D1 (chart " + IntegerToString(chart) + ")";
}

//+------------------------------------------------------------------+
//| One supervisor pass: re-read manifest, deploy each entry,        |
//| log results.                                                     |
//+------------------------------------------------------------------+
void RunSupervisorPass() {
   g_poll_count++;
   if(!LoadManifest()) return;
   int n = ArraySize(g_manifest);
   int ok = 0, fail = 0;
   for(int i = 0; i < n; i++) {
      string ea = g_manifest[i];
      // Skip self -- this EA is BotOrchestrator, attached to whatever chart user picked
      if(ea == "BotOrchestrator") continue;
      string result = DeployEA(ea);
      bool failed = (StringFind(result, "FAIL") == 0);
      if(failed) {
         fail++;
         PrintFormat("[BotOrchestrator] %s: %s", ea, result);
      } else {
         ok++;
         if(InpVerbose || g_poll_count == 1) {
            PrintFormat("[BotOrchestrator] %s: %s", ea, result);
         }
      }
   }
   if(g_poll_count == 1 || g_poll_count % 10 == 0 || fail > 0) {
      PrintFormat("[BotOrchestrator] poll #%d: ok=%d fail=%d total=%d",
                  g_poll_count, ok, fail, n);
   }
}

//+------------------------------------------------------------------+
//| OnInit / OnDeinit                                                 |
//+------------------------------------------------------------------+
int OnInit() {
   PrintFormat("[BotOrchestrator] init: manifest=%s poll=%ds tf=%s auto_save=%s",
               InpManifestFile, InpPollSeconds, EnumToString(InpChartPeriod),
               (string)(InpAutoSaveTemplates ? "true" : "false"));
   // Run one pass immediately so the user sees feedback within 1s
   RunSupervisorPass();
   EventSetTimer(InpPollSeconds);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   PrintFormat("[BotOrchestrator] deinit reason=%d", reason);
   EventKillTimer();
}

void OnTimer() {
   RunSupervisorPass();
}

// We don't need OnTick for this EA but MT5 requires it for non-script
void OnTick() {}
