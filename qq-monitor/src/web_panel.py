"""QQ bot stack component."""




import os
import json
import re
import shutil
import threading
import time
import traceback
from datetime import datetime
from typing import Dict, Any, Optional

from flask import Flask, jsonify, request, render_template_string, send_from_directory
from flask_cors import CORS
from werkzeug.exceptions import NotFound

from .message_store import MessageStore
from .logger import setup_logger

logger = setup_logger("web_panel")




DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>QQ群聊监控系统</title>
<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Microsoft YaHei', -apple-system, sans-serif; background: #f0f2f5; color: #333; }
.header { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 20px 30px; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 10px rgba(0,0,0,.2); }
.header h1 { font-size: 22px; font-weight: 600; }
.header .status { display: flex; gap: 15px; align-items: center; font-size: 14px; }
.status-dot { width: 10px; height: 10px; border-radius: 50%; display: inline-block; margin-right: 5px; }
.status-dot.online { background: #52c41a; box-shadow: 0 0 6px #52c41a; }
.status-dot.offline { background: #ff4d4f; }
.container { max-width: 1400px; margin: 20px auto; padding: 0 20px; }
.tabs { display: flex; gap: 5px; margin-bottom: 20px; background: white; padding: 8px; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); }
.tab { padding: 10px 24px; border-radius: 8px; cursor: pointer; font-size: 14px; font-weight: 500; transition: all .2s; color: #666; border: none; background: none; }
.tab:hover { background: #f0f0f0; }
.tab.active { background: linear-gradient(135deg, #667eea, #764ba2); color: white; }
.card { background: white; border-radius: 10px; box-shadow: 0 1px 4px rgba(0,0,0,.08); padding: 20px; margin-bottom: 20px; }
.card h3 { font-size: 16px; margin-bottom: 15px; color: #333; border-left: 3px solid #667eea; padding-left: 10px; }
.stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 15px; }
.stat-item { background: linear-gradient(135deg, #f5f7fa, #c3cfe2); border-radius: 10px; padding: 18px; text-align: center; }
.stat-item .value { font-size: 28px; font-weight: 700; color: #333; }
.stat-item .label { font-size: 13px; color: #666; margin-top: 5px; }
.toolbar { display: flex; gap: 10px; margin-bottom: 15px; flex-wrap: wrap; align-items: center; }
.toolbar input, .toolbar select { padding: 8px 12px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 13px; outline: none; transition: border-color .2s; }
.toolbar input:focus, .toolbar select:focus { border-color: #667eea; }
.toolbar button { padding: 8px 18px; border: none; border-radius: 6px; cursor: pointer; font-size: 13px; font-weight: 500; transition: all .2s; }
.btn-primary { background: linear-gradient(135deg, #667eea, #764ba2); color: white; }
.btn-primary:hover { opacity: .9; transform: translateY(-1px); }
.btn-secondary { background: #f0f0f0; color: #333; }
.btn-secondary:hover { background: #e0e0e0; }
.btn-danger { background: #ff4d4f; color: white; }
.btn-danger:hover { opacity: .9; }
table { width: 100%; border-collapse: collapse; font-size: 13px; }
table th { background: #fafafa; padding: 10px 12px; text-align: left; font-weight: 600; border-bottom: 2px solid #f0f0f0; white-space: nowrap; }
table td { padding: 10px 12px; border-bottom: 1px solid #f0f0f0; vertical-align: top; }
table tr:hover { background: #f8f9ff; }
.msg-content { max-width: 400px; word-break: break-all; }
.msg-text { color: #333; }
.msg-media { color: #999; font-size: 12px; margin-top: 3px; }
.msg-img-wrap { margin-top: 5px; }
.msg-img { max-width: 150px; max-height: 150px; border-radius: 6px; cursor: pointer; border: 1px solid #eee; transition: transform .2s; }
.msg-img:hover { transform: scale(1.5); z-index: 999; position: relative; box-shadow: 0 4px 12px rgba(0,0,0,.3); }
.msg-media-tag { display: inline-block; background: #f0f0f0; color: #666; padding: 2px 6px; border-radius: 4px; font-size: 12px; margin: 2px 2px; }
.msg-reply { background: #f5f5f5; border-left: 3px solid #ddd; padding: 4px 8px; margin-top: 4px; font-size: 12px; color: #666; border-radius: 0 4px 4px 0; }
.violation-mark { margin-top: 6px; padding: 6px 8px; background: #fff1f0; border-left: 3px solid #ff4d4f; border-radius: 4px; font-size: 12px; color: #a8071a; }
.config-input { width: 100%; padding: 8px; border: 1px solid #d9d9d9; border-radius: 6px; font-size: 13px; }
.help-text { color: #888; font-size: 12px; margin-top: 4px; line-height: 1.6; }
/* 开关按钮样式 */
.switch-row { display: flex; align-items: center; justify-content: space-between; padding: 12px; background: #fafafa; border-radius: 10px; margin-bottom: 8px; transition: all .2s; }
.switch-row:hover { background: #f0f5ff; transform: translateY(-1px); box-shadow: 0 2px 8px rgba(0,0,0,.06); }
.switch-left { display: flex; align-items: center; gap: 12px; flex: 1; min-width: 0; }
.switch-avatar { width: 44px; height: 44px; border-radius: 10px; background: linear-gradient(135deg, #667eea, #764ba2); flex-shrink: 0; display: flex; align-items: center; justify-content: center; color: white; font-weight: bold; font-size: 16px; overflow: hidden; box-shadow: 0 2px 6px rgba(0,0,0,.12); }
.switch-avatar img { width: 100%; height: 100%; object-fit: cover; }
.avatar-text { text-shadow: 0 1px 2px rgba(0,0,0,.2); letter-spacing: 1px; }
.switch-info { flex: 1; min-width: 0; }
.switch-group-name { font-weight: 600; color: #333; font-size: 15px; display: flex; align-items: center; gap: 8px; }
.switch-group-id { color: #999; font-size: 12px; font-weight: normal; }
.switch-group-stats { color: #bbb; font-size: 12px; margin-top: 4px; display: flex; gap: 12px; }
.switch-right { display: flex; align-items: center; gap: 16px; flex-shrink: 0; }
.switch-toggle { position: relative; width: 52px; height: 28px; background: #ccc; border-radius: 14px; cursor: pointer; transition: all .3s; flex-shrink: 0; }
.switch-toggle.active { background: #52c41a; box-shadow: 0 2px 8px rgba(82,196,26,.4); }
.switch-toggle::after { content: ''; position: absolute; top: 3px; left: 3px; width: 22px; height: 22px; background: white; border-radius: 50%; transition: transform .3s; box-shadow: 0 2px 4px rgba(0,0,0,.2); }
.switch-toggle.active::after { transform: translateX(24px); }
.switch-remove { color: #ff4d4f; cursor: pointer; font-size: 12px; opacity: .7; transition: opacity .2s; }
.switch-remove:hover { opacity: 1; text-decoration: underline; }
.severity-high { color: #ff4d4f; font-weight: 600; }
.severity-medium { color: #fa8c16; font-weight: 600; }
.severity-low { color: #faad14; }
.severity-critical { color: #cf1322; font-weight: 700; }
.pagination { display: flex; justify-content: center; gap: 5px; margin-top: 15px; }
.pagination button { padding: 6px 14px; border: 1px solid #d9d9d9; border-radius: 6px; background: white; cursor: pointer; font-size: 13px; }
.pagination button.active { background: #667eea; color: white; border-color: #667eea; }
.pagination button:disabled { opacity: .5; cursor: not-allowed; }
.empty { text-align: center; padding: 40px; color: #999; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 12px; font-weight: 500; }
.badge-high { background: #fff1f0; color: #ff4d4f; }
.badge-medium { background: #fff7e6; color: #fa8c16; }
.badge-low { background: #fffbe6; color: #faad14; }
.badge-critical { background: #ffccc7; color: #cf1322; }
.badge-info { background: #e6f7ff; color: #1890ff; }
.panel { display: none; }
.panel.active { display: block; }
.loading { text-align: center; padding: 20px; color: #999; }
.group-tag { display: inline-block; background: #e6f7ff; color: #1890ff; padding: 2px 8px; border-radius: 4px; font-size: 12px; margin-right: 5px; cursor: pointer; }
.group-tag.active { background: #1890ff; color: white; }
.alert-item { border-left: 4px solid #ff4d4f; padding: 12px 15px; margin-bottom: 10px; background: #fff1f0; border-radius: 0 8px 8px 0; }
.alert-item.medium { border-left-color: #fa8c16; background: #fff7e6; }
.alert-item.low { border-left-color: #faad14; background: #fffbe6; }
</style>
</head>
<body>

<div class="header">
    <h1>QQ群聊监控系统</h1>
    <div class="status">
        <span><span class="status-dot" id="wsStatus"></span><span id="wsStatusText">连接中...</span></span>
        <span id="currentTime"></span>
    </div>
</div>

<div class="container">
    <div class="tabs">
        <button class="tab active" onclick="switchTab('dashboard')">数据概览</button>
        <button class="tab" onclick="switchTab('search')">消息检索</button>
        <button class="tab" onclick="switchTab('messages')">聊天记录</button>
        <button class="tab" onclick="switchTab('alerts')">违规告警</button>
        <button class="tab" onclick="switchTab('groups')">群组管理</button>
        <button class="tab" onclick="switchTab('settings')">系统配置</button>
        <button class="tab" onclick="switchTab('aisettings')">AI设置</button>
        <button class="tab" onclick="switchTab('secondaryai')">二次审核AI</button>
        <button class="tab" onclick="switchTab('companion')">陪聊设置</button>
    </div>

    <!-- 数据概览 -->
    <div class="panel active" id="panel-dashboard">
        <div class="card">
            <h3>系统状态</h3>
            <div class="stats-grid" id="statsGrid">
                <div class="stat-item"><div class="value" id="statGroups">-</div><div class="label">监控群数</div></div>
                <div class="stat-item"><div class="value" id="statMessages">-</div><div class="label">消息总数</div></div>
                <div class="stat-item"><div class="value" id="statAlerts">-</div><div class="label">违规告警</div></div>
                <div class="stat-item"><div class="value" id="statStorage">-</div><div class="label">存储使用</div></div>
                <div class="stat-item"><div class="value" id="statPending">-</div><div class="label">待审查消息</div></div>
                <div class="stat-item"><div class="value" id="statQQSent">-</div><div class="label">QQ通知</div></div>
                <div class="stat-item"><div class="value" id="statEmailSent">-</div><div class="label">邮件通知</div></div>
                <div class="stat-item"><div class="value" id="statPushSent">-</div><div class="label">推送通知</div></div>
            </div>
        </div>
        <div class="card">
            <h3>最近告警</h3>
            <div id="recentAlerts"><div class="empty">暂无告警</div></div>
        </div>
    </div>

    <!-- 消息检索 -->
    <div class="panel" id="panel-search">
        <div class="card">
            <h3>🔍 消息检索</h3>
            <div style="margin-bottom:15px">
                <div style="display:flex;gap:10px;margin-bottom:12px">
                    <input type="text" id="globalSearchInput" placeholder="输入QQ号、昵称或关键词进行搜索..." 
                        style="flex:1;padding:12px 16px;border:2px solid #d9d9d9;border-radius:8px;font-size:15px;outline:none;transition:border-color .2s"
                        onkeypress="if(event.key==='Enter')doGlobalSearch(1)"
                        oninput="onSearchInputChange()">
                    <button class="btn-primary" style="padding:12px 32px;font-size:15px;border-radius:8px" onclick="doGlobalSearch(1)">搜索</button>
                </div>
                <div id="searchHint" style="color:#999;font-size:13px">
                    💡 提示：输入QQ号查询该用户的所有发言 · 输入文字查找相关消息 · 支持按群组和时间筛选
                </div>
            </div>
            
            <div class="toolbar" style="background:#fafafa;padding:12px;border-radius:8px">
                <span style="color:#666">筛选条件：</span>
                <select id="searchGroupFilter" onchange="doGlobalSearch(1)">
                    <option value="">全部群组</option>
                </select>
                <input type="text" id="searchUserFilter" placeholder="QQ号" style="width:120px" onkeypress="if(event.key==='Enter')doGlobalSearch(1)">
                <input type="date" id="searchDateFrom" style="width:140px">
                <span style="color:#999">至</span>
                <input type="date" id="searchDateTo" style="width:140px">
                <button class="btn-secondary" onclick="clearSearchFilters()">清除筛选</button>
            </div>
            
            <div id="searchStats" style="display:none;margin:15px 0;padding:12px 16px;background:#f0f7ff;border-radius:8px;border-left:4px solid #1890ff">
                <span id="searchStatsText"></span>
            </div>
            
            <div id="searchResults"><div class="empty">请输入关键词或QQ号开始搜索</div></div>
            <div id="searchPagination"></div>
        </div>
    </div>

    <!-- 聊天记录 -->
    <div class="panel" id="panel-messages">
        <div class="card">
            <h3>聊天记录查询</h3>
            <div class="toolbar">
                <span>群组筛选:</span>
                <div id="groupFilters"></div>
            </div>
            <div class="toolbar">
                <input type="text" id="searchKeyword" placeholder="搜索关键词..." style="width:200px">
                <input type="text" id="searchUser" placeholder="QQ号" style="width:120px">
                <input type="datetime-local" id="searchStart" style="width:180px">
                <input type="datetime-local" id="searchEnd" style="width:180px">
                <label style="display:flex;align-items:center;gap:5px;font-size:13px;color:#666;cursor:pointer">
                    <input type="checkbox" id="searchOnlyViolations" onchange="searchMessages(1)" style="width:auto">
                    只看违规消息
                </label>
                <button class="btn-primary" onclick="searchMessages(1)">搜索</button>
                <button class="btn-secondary" onclick="resetSearch()">重置</button>
            </div>
            <div id="messagesTable"></div>
            <div id="messagesPagination"></div>
        </div>
    </div>

    <!-- 违规告警 -->
    <div class="panel" id="panel-alerts">
        <div class="card">
            <h3>违规告警记录</h3>
            <div class="toolbar">
                <select id="alertSeverity">
                    <option value="">全部级别</option>
                    <option value="critical">严重</option>
                    <option value="high">高</option>
                    <option value="medium">中</option>
                    <option value="low">低</option>
                </select>
                <select id="alertCategory">
                    <option value="">全部分类</option>
                    <option value="fraud_ad">诈骗广告/引流推广</option>
                    <option value="illegal_trade">违法交易</option>
                    <option value="pornographic">色情低俗</option>
                    <option value="violence_threat">暴力威胁</option>
                    <option value="personal_attack">人身攻击</option>
                    <option value="privacy">隐私泄露</option>
                    <option value="minor_risk">未成年人风险</option>
                    <option value="political">政治敏感</option>
                    <option value="gambling">赌博博彩</option>
                    <option value="spam">恶意刷屏</option>
                    <option value="other">其他风险</option>
                </select>
                <select id="alertSecondary">
                    <option value="">全部复核状态</option>
                    <option value="confirmed">二次复核确认违规</option>
                    <option value="suspected">二次复核疑似违规</option>
                    <option value="likely_false_positive">二次复核可能误报</option>
                    <option value="secondary_unavailable">二次复核不可用</option>
                    <option value="not_reviewed">未二次复核</option>
                </select>
                <select id="alertUser">
                    <option value="">全部用户</option>
                </select>
                <button class="btn-primary" onclick="loadAlerts()">刷新</button>
            </div>
            <div id="alertsList"></div>
        </div>
    </div>

    <!-- 群组管理 -->
    <div class="panel" id="panel-groups">
        <div class="card">
            <h3>监控群组列表</h3>
            <div id="groupsList"></div>
        </div>
    </div>

    <!-- AI设置 -->
    <div class="panel" id="panel-settings">
        <div class="card">
            <h3>系统配置</h3>
            <table style="max-width:760px">
                <tr><td style="padding:10px;font-weight:bold;width:160px;vertical-align:top">监控QQ群</td>
                    <td style="padding:10px">
                        <div id="groupSwitchList" style="margin-bottom:10px">
                            <div style="color:#999;font-size:13px">加载中...</div>
                        </div>
                        <div style="display:flex;gap:8px;margin-bottom:8px">
                            <input class="config-input" id="newGroupInput" placeholder="输入新群号后点击添加" style="flex:1">
                            <button class="btn-secondary" onclick="addMonitorGroup()">添加群聊</button>
                        </div>
                        <div class="help-text">点击开关可单独控制每个群的监控状态；新增群会从下一条新消息开始接收。</div>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">QQ私聊通知</td>
                    <td style="padding:10px">
                        <label><input type="checkbox" id="configQQAlertEnabled"> 启用违规后QQ私聊通知</label>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">通知接收QQ</td>
                    <td style="padding:10px">
                        <input class="config-input" id="configQQRecipients" placeholder="多个QQ号用英文逗号分隔，例如 123456,987654">
                        <div class="help-text">这是接收违规告警的QQ号，不是切换机器人登录账号。机器人登录账号需要在NapCat里切换。</div>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">聊天记录TXT目录</td>
                    <td style="padding:10px">
                        <input class="config-input" id="configExportDir" placeholder="例如 ./聊天记录 或 自定义聊天记录目录">
                        <div class="help-text">这里控制人类可读TXT聊天记录的保存位置。底层JSON数据目录不建议运行中修改。</div>
                    </td></tr>
            </table>
            <div class="toolbar">
                <button class="btn-primary" onclick="saveSystemConfig()">保存系统配置</button>
                <button class="btn-secondary" onclick="loadSystemConfig()">重新加载</button>
                <button class="btn-secondary" onclick="openFolderPicker()">选择文件夹</button>
                <button class="btn-primary" onclick="syncExportNow()">立即同步保存聊天记录</button>
                <button class="btn-primary" onclick="transferExportDir()">一键转移聊天记录目录</button>
                <button class="btn-secondary" onclick="loadPendingFiles()">待确认大文件</button>
                <button class="btn-secondary" onclick="cleanupStorage()">清理/压缩旧存储</button>
                <span id="systemConfigResult"></span>
            </div>
            <div style="margin-top:20px;padding:16px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:8px">
                <strong>📦 附件占用与清理</strong>
                <div style="font-size:12px;color:#888;margin:6px 0 10px">
                    附件（图片/文件/视频/语音）不会被「清理/压缩旧存储」自动删除。这里可以按日期清理它们。
                </div>
                <div id="attachmentStats" style="font-size:13px;color:#555;margin-bottom:10px">点击「查看附件占用」加载统计</div>
                <div class="toolbar" style="margin-bottom:0">
                    <button class="btn-secondary" onclick="loadAttachmentStats()">查看附件占用</button>
                    <span>删除</span>
                    <input type="number" id="attachDays" value="90" min="0" style="width:80px">
                    <span>天前的附件</span>
                    <button class="btn-secondary" onclick="cleanupAttachments(true)">预览</button>
                    <button class="btn-danger" onclick="cleanupAttachments(false)">确认删除</button>
                </div>
                <div id="attachmentResult" style="font-size:13px;margin-top:10px"></div>
            </div>
            <div style="margin-top:20px;padding:16px;background:#fff7e6;border:1px solid #ffd591;border-radius:8px">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <div>
                        <strong style="color:#d46b08">⚠️ 系统重启</strong>
                        <div style="font-size:12px;color:#888;margin-top:4px">重启整个监控系统，包括NapCat连接、AI审查、消息存储等所有模块</div>
                    </div>
                    <button class="btn-danger" style="padding:10px 24px;font-size:14px" onclick="restartSystem()">🔄 一键重启</button>
                </div>
            </div>
            <div id="folderPicker" style="display:none;margin-top:12px;padding:12px;border:1px solid #e8e8e8;border-radius:8px;background:#fafafa">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <strong>选择聊天记录保存目录</strong>
                    <button class="btn-secondary" onclick="closeFolderPicker()">关闭</button>
                </div>
                <div class="help-text" id="folderCurrent"></div>
                <div id="folderList" style="margin-top:8px;max-height:260px;overflow:auto"></div>
            </div>
            <div id="pendingFilesPanel" style="display:none;margin-top:12px;padding:12px;border:1px solid #e8e8e8;border-radius:8px;background:#fafafa">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
                    <strong>待确认大文件</strong>
                    <button class="btn-secondary" onclick="document.getElementById('pendingFilesPanel').style.display='none'">关闭</button>
                </div>
                <div class="help-text">超过1GB的文件会先暂停保存。你也可以私聊机器人回复：保存 文件ID 或 拒绝 文件ID。</div>
                <div id="pendingFilesList" style="margin-top:8px"></div>
            </div>
        </div>
    </div>

    <div class="panel" id="panel-aisettings">
        <div class="card">
            <h3>AI审查配置</h3>
            <div class="toolbar">
                <label style="margin-right:10px">
                    <input type="checkbox" id="aiEnabled" onchange="toggleAI()">
                    启用AI审查
                </label>
                <button class="btn-primary" onclick="saveAIConfig()">保存配置</button>
                <button class="btn-secondary" onclick="testAIConnection()">测试连接</button>
                <button class="btn-secondary" onclick="runAIReviewNow()">立即审查待审查消息</button>
            </div>
            <table style="max-width:700px">
                <tr><td style="padding:10px;font-weight:bold;width:140px">预设方案</td>
                    <td style="padding:10px">
                        <select id="aiPreset" onchange="applyPreset()" style="padding:6px 10px;border:1px solid #d9d9d9;border-radius:6px;width:100%">
                            <option value="">自定义</option>
                            <option value="ollama">本地Ollama</option>
                            <option value="qwen">通义千问API</option>
                        </select>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">API地址</td>
                    <td style="padding:10px"><input type="text" id="aiApiBase" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px" placeholder="http://localhost:11434/v1"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">API Key</td>
                    <td style="padding:10px"><input type="password" id="aiApiKey" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px" placeholder="ollama 或 你的API Key"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">模型名称</td>
                    <td style="padding:10px"><input type="text" id="aiModel" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px" placeholder="qwen2.5"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">审查间隔(分钟)</td>
                    <td style="padding:10px"><input type="number" id="aiInterval" style="width:100px;padding:8px;border:1px solid #d9d9d9;border-radius:6px" min="1" max="60" value="5"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">上下文消息</td>
                    <td style="padding:10px">
                        上文 <input type="number" id="aiContextBefore" style="width:80px;padding:8px;border:1px solid #d9d9d9;border-radius:6px" min="0" max="50" value="3">
                        条，下文 <input type="number" id="aiContextAfter" style="width:80px;padding:8px;border:1px solid #d9d9d9;border-radius:6px" min="0" max="50" value="2"> 条
                        <div class="help-text">AI审查每条目标消息时，会结合指定数量的上下消息，识别拆分广告、前后文攻击、上下文隐私泄露等多条消息关联风险。</div>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">历史消息定时审查</td>
                    <td style="padding:10px">
                        <label style="margin-right:16px">
                            <input type="checkbox" id="aiHistoryReviewEnabled">
                            启用历史消息回溯审查
                        </label>
                        <div style="margin-top:8px;display:flex;gap:12px;align-items:center;flex-wrap:wrap">
                            <span>每</span>
                            <input type="number" id="aiHistoryInterval" style="width:80px;padding:6px;border:1px solid #d9d9d9;border-radius:6px" min="1" max="24" value="2">
                            <span>小时审查一次</span>
                            <span style="margin-left:12px">回溯</span>
                            <input type="number" id="aiHistoryHoursBack" style="width:80px;padding:6px;border:1px solid #d9d9d9;border-radius:6px" min="1" max="168" value="4">
                            <span>小时内的消息</span>
                        </div>
                        <div style="margin-top:8px">
                            <span>每次最多审查</span>
                            <input type="number" id="aiHistoryMaxMessages" style="width:100px;padding:6px;border:1px solid #d9d9d9;border-radius:6px" min="10" max="500" value="150">
                            <span>条</span>
                        </div>
                        <div class="help-text">定期从已保存的历史聊天记录中抽取消息进行审查，结合上下文分析，发现违规会立即通知。可覆盖实时审查遗漏的内容。</div>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">系统提示词</td>
                    <td style="padding:10px"><textarea id="aiPrompt" rows="4" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px;font-size:13px"></textarea></td></tr>
            </table>
            <div id="aiTestResult" style="margin-top:15px"></div>
        </div>
    </div>

    <div class="panel" id="panel-secondaryai">
        <div class="card">
            <h3>二次审核AI配置</h3>
            <div class="toolbar">
                <label style="margin-right:10px">
                    <input type="checkbox" id="secondaryAiEnabled">
                    启用二次AI审核
                </label>
                <button class="btn-primary" onclick="saveSecondaryAIConfig()">保存配置</button>
                <button class="btn-secondary" onclick="testSecondaryAIConnection()">测试连接</button>
            </div>
            <table style="max-width:760px">
                <tr><td style="padding:10px;font-weight:bold;width:150px">预设方案</td>
                    <td style="padding:10px">
                        <select id="secondaryAiPreset" onchange="applySecondaryPreset()" style="padding:6px 10px;border:1px solid #d9d9d9;border-radius:6px;width:100%">
                            <option value="">自定义</option>
                            <option value="ollama">本地Ollama</option>
                            <option value="qwen">通义千问API</option>
                        </select>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">API地址</td>
                    <td style="padding:10px"><input type="text" id="secondaryAiApiBase" class="config-input" placeholder="http://localhost:11434/v1"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">API Key</td>
                    <td style="padding:10px"><input type="password" id="secondaryAiApiKey" class="config-input" placeholder="ollama 或 你的API Key"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">模型名称</td>
                    <td style="padding:10px"><input type="text" id="secondaryAiModel" class="config-input" placeholder="qwen2.5"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">系统提示词</td>
                    <td style="padding:10px"><textarea id="secondaryAiPrompt" rows="4" class="config-input" style="font-size:13px"></textarea>
                    <div class="help-text">二次审核只处理首次AI已经判定有风险的消息。这里可以使用更强、更慢或更贵的模型。</div></td></tr>
            </table>
            <div id="secondaryAiResult" style="margin-top:15px"></div>
        </div>
    </div>

    <div class="panel" id="panel-companion">
        <div class="card">
            <h3>陪聊设置</h3>
            <p style="color:#666;font-size:13px;margin-bottom:12px">当群成员@机器人时，AI会自动生成回复。使用二次审核AI的模型配置。</p>
            <div class="toolbar">
                <label style="margin-right:10px">
                    <input type="checkbox" id="companionEnabled">
                    启用陪聊
                </label>
                <button class="btn-primary" onclick="saveCompanionConfig()">保存配置</button>
                <button class="btn-secondary" onclick="testCompanionConnection()">测试连接</button>
            </div>
            <table style="max-width:760px">
                <tr><td style="padding:10px;font-weight:bold;width:150px">机器人昵称</td>
                    <td style="padding:10px"><input type="text" id="companionBotName" style="width:200px;padding:8px;border:1px solid #d9d9d9;border-radius:6px" placeholder="小助手"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">API地址</td>
                    <td style="padding:10px"><input type="text" id="companionApiBase" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px" placeholder="留空则使用二次审核AI的API地址"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">API Key</td>
                    <td style="padding:10px"><input type="password" id="companionApiKey" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px" placeholder="留空则使用二次审核AI的Key"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">模型名称</td>
                    <td style="padding:10px"><input type="text" id="companionModel" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px" placeholder="留空则使用二次审核AI的模型"></td></tr>
                <tr><td style="padding:10px;font-weight:bold">回复冷却(秒)</td>
                    <td style="padding:10px">
                        <input type="number" id="companionCooldown" style="width:100px;padding:8px;border:1px solid #d9d9d9;border-radius:6px" min="1" max="300" value="10">
                        <div class="help-text">同一群内两次回复的最小间隔，避免刷屏</div>
                    </td></tr>
                <tr><td style="padding:10px;font-weight:bold">系统提示词</td>
                    <td style="padding:10px">
                        <textarea id="companionPrompt" rows="4" style="width:100%;padding:8px;border:1px solid #d9d9d9;border-radius:6px;font-size:13px" placeholder="留空使用默认提示词"></textarea>
                        <div class="help-text">定义AI的性格和回复风格，留空则使用默认的活泼友好风格</div>
                    </td></tr>
            </table>
            <div id="companionTestResult" style="margin-top:15px"></div>
        </div>
    </div>

</div>

<script>
const API = '';
let currentGroup = null;
let currentPage = 1;

function updateTime() {
    document.getElementById('currentTime').textContent = new Date().toLocaleString('zh-CN');
}
setInterval(updateTime, 1000);
updateTime();

function switchTab(name) {
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    event.target.classList.add('active');
    document.getElementById('panel-' + name).classList.add('active');
    if (name === 'dashboard') loadDashboard();
    if (name === 'search') { initSearchGroups(); }
    if (name === 'messages') { loadGroupFilters(); searchMessages(1); }
    if (name === 'alerts') { loadAlertUsers(); loadAlerts(); }
    if (name === 'groups') loadGroups();
    if (name === 'settings') loadSystemConfig();
    if (name === 'aisettings') loadAISettings();
    if (name === 'secondaryai') loadSecondaryAISettings();
    if (name === 'companion') loadCompanionSettings();
}

async function api(url, opts = {}) {
    try {
        const resp = await fetch(API + url, opts);
        return await resp.json();
    } catch(e) {
        console.error('API error:', e);
        return { error: e.message };
    }
}

async function loadDashboard() {
    const data = await api('/api/stats');
    if (data.error) return;
    document.getElementById('statGroups').textContent = data.total_groups || 0;
    document.getElementById('statMessages').textContent = data.total_messages || 0;
    document.getElementById('statAlerts').textContent = data.total_alerts || 0;
    document.getElementById('statStorage').textContent = data.storage_used_mb == null ? '计算中' : data.storage_used_mb.toFixed(1) + ' MB';
    document.getElementById('statPending').textContent = data.pending_review || 0;
    document.getElementById('statQQSent').textContent = data.alert_stats?.qq_sent || 0;
    document.getElementById('statEmailSent').textContent = data.alert_stats?.email_sent || 0;
    document.getElementById('statPushSent').textContent = data.alert_stats?.push_sent || 0;

    // WS状态
    const wsOnline = data.ws_connected;
    document.getElementById('wsStatus').className = 'status-dot ' + (wsOnline ? 'online' : 'offline');
    document.getElementById('wsStatusText').textContent = wsOnline ? '已连接' : '未连接';

    // 最近告警
    const alerts = await api('/api/alerts?limit=5');
    const container = document.getElementById('recentAlerts');
    if (alerts.length === 0) {
        container.innerHTML = '<div class="empty">暂无告警</div>';
    } else {
        container.innerHTML = alerts.map(a => renderAlertItem(a)).join('');
    }
}

async function loadGroupFilters() {
    const groups = await api('/api/groups');
    const container = document.getElementById('groupFilters');
    container.innerHTML = '<span class="group-tag ' + (currentGroup === null ? 'active' : '') + '" onclick="selectGroup(null)">全部</span>' +
        groups.map(g => `<span class="group-tag ${currentGroup === g.group_id ? 'active' : ''}" onclick="selectGroup(${g.group_id})">群${g.group_id} (${g.message_count})</span>`).join('');
}

function selectGroup(gid) {
    currentGroup = gid;
    loadGroupFilters();
    searchMessages(1);
}

async function searchMessages(page) {
    currentPage = page;
    const params = new URLSearchParams({
        page: page,
        page_size: 50,
        keyword: document.getElementById('searchKeyword').value,
        user_id: document.getElementById('searchUser').value,
        start_time: document.getElementById('searchStart').value.replace('T', ' '),
        end_time: document.getElementById('searchEnd').value.replace('T', ' '),
    });
    if (currentGroup !== null) params.set('group_id', currentGroup);
    params.set('include_alerts', '1');
    if (document.getElementById('searchOnlyViolations').checked) {
        params.set('only_violations', '1');
    }

    const data = await api('/api/messages?' + params.toString());
    const container = document.getElementById('messagesTable');

    if (!data.messages || data.messages.length === 0) {
        container.innerHTML = '<div class="empty">暂无聊天记录</div>';
        document.getElementById('messagesPagination').innerHTML = '';
        return;
    }

    let html = '<table><thead><tr><th>时间</th><th>群号</th><th>发送者</th><th>内容</th></tr></thead><tbody>';
    data.messages.forEach(m => {
        const content = m.content || {};
        const text = (content.text || '').replace(/</g, '&lt;');
        const segs = content.segments || [];

        // 构建媒体HTML
        let mediaHtml = '';
        segs.forEach(s => {
            if (s.type === 'image') {
                // 2026-09-22：图片地址来自消息内容（群友可控），原来直接塞进 src="..."，
                // 一个带引号的路径就能顶出属性、注入脚本。这里只留安全字符。
                const imgSrc = safeAttr(s.local_path || s.url || '');
                if (imgSrc) {
                    mediaHtml += `<div class="msg-img-wrap"><img class="msg-img" src="${imgSrc}" onclick="window.open(this.src)" onerror="this.style.display='none'"></div>`;
                } else {
                    mediaHtml += '<span class="msg-media-tag">[图片]</span>';
                }
            } else if (s.type === 'face') {
                mediaHtml += `<span class="msg-media-tag">[表情:${escapeHtml(s.data?.id || '')}]</span>`;
            } else if (s.type === 'reply') {
                mediaHtml += `<div class="msg-reply">回复: ${escapeHtml(s.data?.msg_preview || '')}</div>`;
            } else if (s.type !== 'text' && s.summary) {
                mediaHtml += `<span class="msg-media-tag">${escapeHtml(s.summary)}</span>`;
            }
        });

        const violation = m.violation_summary || null;
        const violationHtml = violation ? `<div class="violation-mark">
            违规：${String(categoryLabel(violation.category, violation.category_label)).replace(/</g,'&lt;')}
            · ${String(violation.violation_type || '').replace(/</g,'&lt;')}
            · ${String(violation.secondary_status_label || '未二次复核').replace(/</g,'&lt;')}
        </div>` : '';

        html += `<tr>
            <td style="white-space:nowrap">${m.datetime || ''}</td>
            <td>群${m.group_id || ''}</td>
            <td><strong>${(m.card || m.nickname || '未知').replace(/</g,'&lt;')}</strong><br><small style="color:#999">QQ:${m.user_id || ''}</small></td>
            <td class="msg-content"><div class="msg-text">${text}</div>${mediaHtml}${violationHtml}</td>
        </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;

    // 分页
    const total = data.total_pages || 1;
    let pagHtml = '<div class="pagination">';
    pagHtml += `<button ${page <= 1 ? 'disabled' : ''} onclick="searchMessages(${page-1})">上一页</button>`;
    for (let i = Math.max(1, page-3); i <= Math.min(total, page+3); i++) {
        pagHtml += `<button class="${i === page ? 'active' : ''}" onclick="searchMessages(${i})">${i}</button>`;
    }
    pagHtml += `<button ${page >= total ? 'disabled' : ''} onclick="searchMessages(${page+1})">下一页</button>`;
    pagHtml += `<span style="margin-left:10px;color:#999">共 ${data.total} 条</span>`;
    pagHtml += '</div>';
    document.getElementById('messagesPagination').innerHTML = pagHtml;
}

function resetSearch() {
    document.getElementById('searchKeyword').value = '';
    document.getElementById('searchUser').value = '';
    document.getElementById('searchStart').value = '';
    document.getElementById('searchEnd').value = '';
    document.getElementById('searchOnlyViolations').checked = false;
    currentGroup = null;
    searchMessages(1);
}

// ===== 消息检索功能 =====
let currentSearchPage = 1;

function onSearchInputChange() {
    const input = document.getElementById('globalSearchInput').value.trim();
    const hint = document.getElementById('searchHint');
    if (!input) {
        hint.innerHTML = '💡 提示：输入QQ号查询该用户的所有发言 · 输入文字查找相关消息 · 支持按群组和时间筛选';
        return;
    }
    // 智能识别输入类型
    if (/^\d{5,12}$/.test(input)) {
        hint.innerHTML = `🔍 检测到QQ号：<strong>${input}</strong>，将搜索该用户的所有发言记录`;
    } else {
        hint.innerHTML = `🔍 将搜索包含 "<strong>${escapeHtml(input)}</strong>" 的所有消息`;
    }
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// 属性（src="..."）里不能只靠 escapeHtml —— 它不转义引号。
// 消息里的图片地址是群友可控的，所以这里只保留安全字符。
function safeAttr(text) {
    return String(text == null ? '' : text).replace(/["'<>`\\\s]/g, '');
}

function highlightKeyword(text, keyword) {
    if (!keyword || !text) return escapeHtml(text || '');
    try {
        const safeKeyword = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        return escapeHtml(text).replace(new RegExp(safeKeyword, 'gi'), m => `<mark style="background:#fff3bf;padding:1px 3px;border-radius:3px;color:#d48806">${m}</mark>`);
    } catch(e) {
        return escapeHtml(text);
    }
}

async function initSearchGroups() {
    const sel = document.getElementById('searchGroupFilter');
    const groups = await api('/api/groups') || [];
    sel.innerHTML = '<option value="">全部群组</option>' + groups.map(g => 
        `<option value="${g.group_id}">群${g.group_id} (${g.message_count}条)</option>`
    ).join('');
}

async function doGlobalSearch(page) {
    currentSearchPage = page || 1;
    const query = document.getElementById('globalSearchInput').value.trim();
    const userFilter = document.getElementById('searchUserFilter').value.trim();
    const groupFilter = document.getElementById('searchGroupFilter').value;
    const dateFrom = document.getElementById('searchDateFrom').value;
    const dateTo = document.getElementById('searchDateTo').value;
    
    const container = document.getElementById('searchResults');
    const statsDiv = document.getElementById('searchStats');
    
    if (!query && !userFilter && !groupFilter && !dateFrom && !dateTo) {
        container.innerHTML = '<div class="empty">请输入搜索条件</div>';
        document.getElementById('searchPagination').innerHTML = '';
        statsDiv.style.display = 'none';
        return;
    }
    
    container.innerHTML = '<div class="loading">搜索中...</div>';
    
    const params = new URLSearchParams({
        page: currentSearchPage,
        page_size: 30,
        include_alerts: '1'
    });
    
    // 智能识别：纯数字QQ号
    if (query && /^\d{5,12}$/.test(query)) {
        params.set('user_id', query);
    } else if (query) {
        params.set('keyword', query);
    }
    
    if (userFilter) params.set('user_id', userFilter);
    if (groupFilter) params.set('group_id', groupFilter);
    if (dateFrom) params.set('start_time', dateFrom + ' 00:00:00');
    if (dateTo) params.set('end_time', dateTo + ' 23:59:59');
    
    try {
        const data = await api('/api/messages?' + params.toString());
        
        if (!data.messages || data.messages.length === 0) {
            container.innerHTML = '<div class="empty">未找到匹配的消息</div>';
            document.getElementById('searchPagination').innerHTML = '';
            statsDiv.style.display = 'none';
            return;
        }
        
        // 统计信息
        const keyword = (query && !/^\d{5,12}$/.test(query)) ? query : '';
        const searchUserId = userFilter || (/^\d{5,12}$/.test(query) ? query : '');
        const uniqueUsers = new Set(data.messages.map(m => m.user_id));
        const uniqueGroups = new Set(data.messages.map(m => m.group_id));
        
        let statsText = `📊 共找到 <strong>${data.total}</strong> 条匹配消息`;
        if (searchUserId) statsText += `，来自QQ号 <strong>${searchUserId}</strong>`;
        statsText += `，涉及 <strong>${uniqueGroups.size}</strong> 个群，<strong>${uniqueUsers.size}</strong> 位用户`;
        document.getElementById('searchStatsText').innerHTML = statsText;
        statsDiv.style.display = 'block';
        
        // 渲染结果
        let html = '<table><thead><tr><th style="width:150px">时间</th><th style="width:100px">群号</th><th style="width:140px">发送者</th><th>消息内容</th></tr></thead><tbody>';
        
        data.messages.forEach(m => {
            const content = m.content || {};
            const text = content.text || '';
            const segs = content.segments || [];
            const cardOrNick = m.card || m.nickname || '未知';
            
            // 高亮搜索词
            const highlightedText = keyword ? highlightKeyword(text, keyword) : escapeHtml(text);
            const highlightedName = keyword ? highlightKeyword(cardOrNick, keyword) : escapeHtml(cardOrNick);
            
            // 构建媒体HTML
            let mediaHtml = '';
            segs.forEach(s => {
                if (s.type === 'image') {
                    const imgSrc = safeAttr(s.local_path || s.url || '');
                    if (imgSrc) {
                        mediaHtml += `<div class="msg-img-wrap"><img class="msg-img" src="${imgSrc}" onclick="window.open(this.src)" onerror="this.style.display='none'"></div>`;
                    } else {
                        mediaHtml += '<span class="msg-media-tag">[图片]</span>';
                    }
                } else if (s.type === 'face') {
                    mediaHtml += `<span class="msg-media-tag">[表情]</span>`;
                } else if (s.type === 'reply') {
                    const preview = s.data?.msg_preview || '';
                    mediaHtml += `<div class="msg-reply">回复: ${keyword ? highlightKeyword(preview, keyword) : escapeHtml(preview)}</div>`;
                } else if (s.type === 'at') {
                    mediaHtml += `<span class="msg-media-tag">@${escapeHtml(s.name || s.qq || '')}</span>`;
                } else if (s.type !== 'text' && s.summary) {
                    mediaHtml += `<span class="msg-media-tag">${escapeHtml(s.summary)}</span>`;
                }
            });
            
            const violation = m.violation_summary || null;
            const violationHtml = violation ? `<div class="violation-mark">
                违规：${escapeHtml(violation.category_label || violation.category || '')}
            </div>` : '';
            
            html += `<tr>
                <td style="white-space:nowrap;font-size:12px;color:#666">${escapeHtml(m.datetime || '')}</td>
                <td style="font-size:12px">群${m.group_id || ''}</td>
                <td><strong>${highlightedName}</strong><br><small style="color:#999">QQ:${m.user_id || ''}</small></td>
                <td class="msg-content"><div class="msg-text">${highlightedText || '<span style="color:#bbb">[无文字内容]</span>'}</div>${mediaHtml}${violationHtml}</td>
            </tr>`;
        });
        
        html += '</tbody></table>';
        container.innerHTML = html;
        
        // 分页
        const total = data.total_pages || 1;
        let pagHtml = '<div class="pagination">';
        pagHtml += `<button ${currentSearchPage <= 1 ? 'disabled' : ''} onclick="doGlobalSearch(${currentSearchPage-1})">上一页</button>`;
        for (let i = Math.max(1, currentSearchPage-3); i <= Math.min(total, currentSearchPage+3); i++) {
            pagHtml += `<button class="${i === currentSearchPage ? 'active' : ''}" onclick="doGlobalSearch(${i})">${i}</button>`;
        }
        pagHtml += `<button ${currentSearchPage >= total ? 'disabled' : ''} onclick="doGlobalSearch(${currentSearchPage+1})">下一页</button>`;
        pagHtml += `<span style="margin-left:10px;color:#999">第 ${currentSearchPage}/${total} 页 · 共 ${data.total} 条</span>`;
        pagHtml += '</div>';
        document.getElementById('searchPagination').innerHTML = pagHtml;
        
    } catch(e) {
        container.innerHTML = `<div class="empty">搜索失败：${escapeHtml(e.message || '未知错误')}</div>`;
    }
}

function clearSearchFilters() {
    document.getElementById('searchUserFilter').value = '';
    document.getElementById('searchGroupFilter').value = '';
    document.getElementById('searchDateFrom').value = '';
    document.getElementById('searchDateTo').value = '';
    if (document.getElementById('globalSearchInput').value.trim()) {
        doGlobalSearch(1);
    }
}

async function loadAlerts() {
    const severity = document.getElementById('alertSeverity').value;
    const category = document.getElementById('alertCategory').value;
    const secondary = document.getElementById('alertSecondary').value;
    const user = document.getElementById('alertUser').value;
    const params = new URLSearchParams({ limit: 100 });
    if (severity) params.set('severity', severity);
    if (category) params.set('category', category);
    if (secondary) params.set('secondary_status', secondary);
    if (user) params.set('user_id', user);
    const alerts = await api('/api/alerts?' + params.toString());
    const container = document.getElementById('alertsList');

    if (!alerts || alerts.length === 0) {
        container.innerHTML = '<div class="empty">暂无告警记录</div>';
        return;
    }
    container.innerHTML = alerts.map(a => renderAlertItem(a)).join('');
}

async function loadAlertUsers() {
    const users = await api('/api/alerts/users');
    const sel = document.getElementById('alertUser');
    const current = sel.value;
    sel.innerHTML = '<option value="">全部用户</option>' + (users || []).map(u => {
        const name = String(u.nickname || '未知').replace(/</g,'&lt;');
        return `<option value="${u.user_id}">${name} (QQ:${u.user_id}) · ${u.count}条</option>`;
    }).join('');
    sel.value = current;
}

function renderAlertItem(a) {
    const msg = a.message || {};
    const sevClass = a.severity || 'medium';
    const time = a.review_time || a.time || '';
    const groupId = msg.group_id || a.group_id || '?';
    const userId = msg.user_id || a.user_id || '?';
    const nickname = msg.card || msg.nickname || a.card || a.nickname || '未知';
    const msgTime = msg.datetime || a.datetime || '';

    // 优先显示原始消息全文，AI摘要作为补充
    const originalText = msg.content?.text || '';
    const aiPreview = a.content_preview || '';
    const matchedWord = a.matched_word || '';
    const showOriginal = originalText && originalText !== aiPreview;
    const content = originalText || aiPreview || matchedWord || '';

    // 构建媒体HTML（图片等）
    let mediaHtml = '';
    const segs = msg.content?.segments || [];
    segs.forEach(s => {
        if (s.type === 'image') {
            const imgSrc = safeAttr(s.local_path || s.url || '');
            if (imgSrc) {
                mediaHtml += `<div class="msg-img-wrap"><img class="msg-img" src="${imgSrc}" onclick="window.open(this.src)" onerror="this.style.display='none'" style="max-height:120px;max-width:200px;border-radius:4px;margin-top:4px"></div>`;
            }
        } else if (s.type === 'face') {
            mediaHtml += `<span class="msg-media-tag">[表情]</span>`;
        } else if (s.type === 'reply') {
            mediaHtml += `<div class="msg-reply" style="font-size:12px;color:#888;border-left:2px solid #d9d9d9;padding-left:6px;margin-top:4px">回复: ${escapeHtml(s.data?.msg_preview || '')}</div>`;
        } else if (s.type !== 'text' && s.summary) {
            mediaHtml += `<span class="msg-media-tag">${escapeHtml(s.summary)}</span>`;
        }
    });

    const category = categoryLabel(a.category, a.category_label);
    const secondary = a.secondary_status_label || '未二次复核';
    const reportBasis = a.report_basis_label || '按当前结果上报';
    const notifyText = a.should_notify === false ? '不通知' : (a.notified ? '已通知' : '未通知');

    // 反馈状态
    const feedback = a.user_feedback || '';
    const feedbackLabel = feedback === 'confirmed' ? '已确认违规' : (feedback === 'false_positive' ? '已标记误报' : '');

    // 告警ID用于反馈（2026-09-22：id 属性里也只用安全字符，别让构造出来的 id 顶出属性）
    const alertId = a.alert_id || a.id || '';
    const safeAlertId = String(alertId).replace(/[^A-Za-z0-9_-]/g, '');

    return `<div class="alert-item ${sevClass}" id="alert-${safeAlertId}">
        <div style="display:flex;justify-content:space-between;align-items:center">
            <strong><span class="badge badge-${sevClass}">${sevClass.toUpperCase()}</span> ${escapeHtml(category)} · ${escapeHtml(a.violation_type || a.type || '未知')}</strong>
            <small style="color:#999">${escapeHtml(time)}</small>
        </div>
        <div style="margin-top:6px;font-size:12px;color:#555">
            <span>二次复核：${String(secondary).replace(/</g,'&lt;')}</span> ·
            <span>上报依据：${String(reportBasis).replace(/</g,'&lt;')}</span> ·
            <span>通知状态：${notifyText}</span>
            ${feedbackLabel ? ` · <span style="color:${feedback === 'confirmed' ? '#cf1322' : '#52c41a'};font-weight:bold">${feedbackLabel}</span>` : ''}
        </div>
        <div style="margin-top:8px">
            <span>群${escapeHtml(groupId)}</span> ·
            <span>${escapeHtml(String(nickname))}</span> (QQ:${escapeHtml(userId)}) ·
            <span>${escapeHtml(msgTime)}</span>
        </div>
        <div style="margin-top:6px;padding:8px;background:rgba(255,255,255,.6);border-radius:4px">
            <div class="msg-text">${String(content).replace(/</g,'&lt;')}</div>
            ${mediaHtml}
        </div>
        ${showOriginal && aiPreview ? `<div style="margin-top:4px;font-size:11px;color:#999;padding:4px 8px;background:rgba(0,0,0,.03);border-radius:4px">AI摘要：${String(aiPreview).replace(/</g,'&lt;')}</div>` : ''}
        ${a.reason ? '<div style="margin-top:4px;font-size:12px;color:#666">判定: ' + a.reason.replace(/</g,'&lt;') + '</div>' : ''}
        ${a.secondary_reason ? '<div style="margin-top:4px;font-size:12px;color:#3b5bdb">二次复核: ' + a.secondary_reason.replace(/</g,'&lt;') + '</div>' : ''}
        ${safeAlertId ? `<div style="margin-top:8px;display:flex;gap:8px">
            <button class="btn-secondary" style="font-size:12px;padding:4px 12px" onclick="feedbackAlert('${safeAlertId}','confirmed')">确认违规</button>
            <button class="btn-secondary" style="font-size:12px;padding:4px 12px" onclick="feedbackAlert('${safeAlertId}','false_positive')">标记误报</button>
        </div>` : ''}
    </div>`;
}

async function feedbackAlert(alertId, feedback) {
    const result = await api('/api/alerts/' + alertId + '/feedback', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({feedback: feedback})
    });
    if (result.success) {
        loadAlerts();
    } else {
        alert('反馈失败: ' + (result.error || '未知错误'));
    }
}

async function loadGroups() {
    const groups = await api('/api/groups');
    const container = document.getElementById('groupsList');
    if (!groups || groups.length === 0) {
        container.innerHTML = '<div class="empty">暂无监控群组</div>';
        return;
    }
    let html = '<table><thead><tr><th>群号</th><th>消息数</th><th>最新消息</th><th>可查日期</th></tr></thead><tbody>';
    groups.forEach(g => {
        html += `<tr>
            <td><strong>群${g.group_id}</strong></td>
            <td>${g.message_count}</td>
            <td>${g.latest_message || '-'}</td>
            <td>${g.available_dates ? g.available_dates.slice(0,5).join(', ') : '-'}</td>
        </tr>`;
    });
    html += '</tbody></table>';
    container.innerHTML = html;
}

// 初始化
loadDashboard();

// ==================== AI设置 ====================
const AI_PRESETS = {
    ollama: { api_base: 'http://localhost:11434/v1', api_key: 'ollama', model: 'qwen2.5' },
    qwen: { api_base: 'https://dashscope.aliyuncs.com/compatible-mode/v1', api_key: '', model: 'qwen-plus' }
};

const CATEGORY_LABELS = {
    fraud_ad: '诈骗广告/引流推广',
    illegal_trade: '违法交易',
    pornographic: '色情低俗',
    violence_threat: '暴力威胁',
    personal_attack: '人身攻击',
    privacy: '隐私泄露',
    minor_risk: '未成年人风险',
    political: '政治敏感',
    gambling: '赌博博彩',
    spam: '恶意刷屏',
    other: '其他风险'
};

function categoryLabel(value, label) {
    return label || CATEGORY_LABELS[value] || '其他风险';
}

function loadAISettings() {
    api('/api/ai/config').then(data => {
        document.getElementById('aiEnabled').checked = data.enabled;
        document.getElementById('aiApiBase').value = data.api_base || '';
        document.getElementById('aiApiKey').value = data.api_key || '';
        document.getElementById('aiModel').value = data.model || '';
        document.getElementById('aiInterval').value = data.review_interval_minutes || 5;
        document.getElementById('aiContextBefore').value = data.context_before_messages ?? 3;
        document.getElementById('aiContextAfter').value = data.context_after_messages ?? 2;
        document.getElementById('aiPrompt').value = data.system_prompt || '';
        // 历史消息审查配置
        document.getElementById('aiHistoryReviewEnabled').checked = data.history_review_enabled ?? true;
        document.getElementById('aiHistoryInterval').value = data.history_review_interval_hours ?? 2;
        document.getElementById('aiHistoryHoursBack').value = data.history_review_hours_back ?? 4;
        document.getElementById('aiHistoryMaxMessages').value = data.history_review_max_messages ?? 150;
        // 检测预设
        const presetSel = document.getElementById('aiPreset');
        presetSel.value = '';
        for (const [k, v] of Object.entries(AI_PRESETS)) {
            if (data.api_base === v.api_base && data.model === v.model) {
                presetSel.value = k; break;
            }
        }
    });
}

function applyPreset() {
    const preset = document.getElementById('aiPreset').value;
    if (!preset || !AI_PRESETS[preset]) return;
    const p = AI_PRESETS[preset];
    document.getElementById('aiApiBase').value = p.api_base;
    document.getElementById('aiApiKey').value = p.api_key;
    document.getElementById('aiModel').value = p.model;
}

function applySecondaryPreset() {
    const preset = document.getElementById('secondaryAiPreset').value;
    if (!preset || !AI_PRESETS[preset]) return;
    const p = AI_PRESETS[preset];
    document.getElementById('secondaryAiApiBase').value = p.api_base;
    document.getElementById('secondaryAiApiKey').value = p.api_key;
    document.getElementById('secondaryAiModel').value = p.model;
}

async function loadSecondaryAISettings() {
    const data = await api('/api/secondary-ai/config');
    if (data.error) return;
    document.getElementById('secondaryAiEnabled').checked = data.enabled !== false;
    document.getElementById('secondaryAiApiBase').value = data.api_base || '';
    document.getElementById('secondaryAiApiKey').value = data.api_key || '';
    document.getElementById('secondaryAiModel').value = data.model || '';
    document.getElementById('secondaryAiPrompt').value = data.system_prompt || '';

    const presetSel = document.getElementById('secondaryAiPreset');
    presetSel.value = '';
    for (const [k, v] of Object.entries(AI_PRESETS)) {
        if (data.api_base === v.api_base && data.model === v.model) {
            presetSel.value = k; break;
        }
    }
}

async function saveSecondaryAIConfig() {
    const payload = {
        enabled: document.getElementById('secondaryAiEnabled').checked,
        api_base: document.getElementById('secondaryAiApiBase').value.trim(),
        api_key: document.getElementById('secondaryAiApiKey').value.trim(),
        model: document.getElementById('secondaryAiModel').value.trim(),
        system_prompt: document.getElementById('secondaryAiPrompt').value.trim()
    };
    const result = await api('/api/secondary-ai/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    const el = document.getElementById('secondaryAiResult');
    if (result.success) {
        el.innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">' + result.message + '</div>';
    } else {
        el.innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">' + (result.message || result.error || '').replace(/</g,'&lt;') + '</div>';
    }
}

async function testSecondaryAIConnection() {
    const el = document.getElementById('secondaryAiResult');
    el.innerHTML = '<div style="padding:10px;color:#999">正在测试二次审核AI连接...</div>';
    await saveSecondaryAIConfig();
    const result = await api('/api/secondary-ai/test', {method: 'POST'});
    if (result.success) {
        el.innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">连接成功! 模型回复: ' + (result.response || '').replace(/</g,'&lt;') + '</div>';
    } else {
        el.innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">连接失败: ' + (result.error || '').replace(/</g,'&lt;') + '</div>';
    }
}

async function loadCompanionSettings() {
    const data = await api('/api/companion/config');
    if (data.error) return;
    document.getElementById('companionEnabled').checked = !!data.enabled;
    document.getElementById('companionBotName').value = data.bot_name || '小助手';
    document.getElementById('companionApiBase').value = data.api_base || '';
    document.getElementById('companionApiKey').value = data.api_key || '';
    document.getElementById('companionModel').value = data.model || '';
    document.getElementById('companionCooldown').value = data.cooldown_seconds || 10;
    document.getElementById('companionPrompt').value = data.system_prompt || '';
}

async function saveCompanionConfig() {
    const config = {
        enabled: document.getElementById('companionEnabled').checked,
        bot_name: document.getElementById('companionBotName').value || '小助手',
        api_base: document.getElementById('companionApiBase').value,
        api_key: document.getElementById('companionApiKey').value,
        model: document.getElementById('companionModel').value,
        cooldown_seconds: parseInt(document.getElementById('companionCooldown').value) || 10,
        system_prompt: document.getElementById('companionPrompt').value
    };
    const result = await api('/api/companion/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(config)
    });
    if (result.success) {
        document.getElementById('companionTestResult').innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">陪聊配置已保存</div>';
    } else {
        document.getElementById('companionTestResult').innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">保存失败: ' + (result.error || '').replace(/</g,'&lt;') + '</div>';
    }
}

async function testCompanionConnection() {
    const el = document.getElementById('companionTestResult');
    el.innerHTML = '<div style="padding:10px;color:#999">正在测试陪聊AI连接...</div>';
    await saveCompanionConfig();
    const result = await api('/api/companion/test', {method: 'POST'});
    if (result.success) {
        el.innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">连接成功! AI回复: ' + (result.response || '').replace(/</g,'&lt;') + '</div>';
    } else {
        el.innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">连接失败: ' + (result.error || '').replace(/</g,'&lt;') + '</div>';
    }
}

function parseIdList(text) {
    return (text || '').split(/[,，\s]+/)
        .map(x => x.trim())
        .filter(Boolean)
        .map(x => Number(x))
        .filter(x => Number.isInteger(x) && x > 0);
}

async function loadSystemConfig() {
    const data = await api('/api/system/config');
    if (data.error) return;
    document.getElementById('configQQAlertEnabled').checked = !!data.qq_alert_enabled;
    document.getElementById('configQQRecipients').value = (data.qq_recipients || []).join(', ');
    document.getElementById('configExportDir').value = data.export_dir || '';
    
    // 加载群列表并渲染开关
    loadGroupSwitchList();
}

async function loadGroupSwitchList() {
    const container = document.getElementById('groupSwitchList');
    try {
        const data = await api('/api/groups/info');
        const groups = data.groups || [];
        
        if (groups.length === 0) {
            container.innerHTML = '<div style="color:#999;font-size:13px">暂无群聊，请在下方添加</div>';
            return;
        }
        
        let html = '';
        for (const g of groups) {
            const activeClass = g.is_monitored ? 'active' : '';
            const statusText = g.is_monitored ? '监控中' : '未监控';
            const statusColor = g.is_monitored ? '#52c41a' : '#999';
            const msgText = g.message_count > 0 ? `${g.message_count} 条消息` : '暂无消息';
            const daysText = g.date_files > 0 ? `${g.date_files} 天记录` : '';
            const membersText = g.member_count > 0 ? `${g.member_count} 人` : '';
            
            // 群头像 - 用群名第一个字 + 渐变色
            const colors = ['#667eea,#764ba2', '#f093fb,#f5576c', '#4facfe,#00f2fe', '#43e97b,#38f9d7', '#fa709a,#fee140', '#30cfd0,#330867', '#ff9a9e,#fecfef', '#667eea,#764ba2'];
            const colorIndex = g.group_id % colors.length;
            const gradient = colors[colorIndex];
            
            // 取群名第一个字作为头像文字
            const avatarText = g.group_name ? g.group_name.charAt(0) : '群';
            
            html += `
                <div class="switch-row">
                    <div class="switch-left">
                        <div class="switch-avatar" style="background: linear-gradient(135deg, ${gradient})">
                            <span class="avatar-text">${avatarText}</span>
                        </div>
                        <div class="switch-info">
                            <div class="switch-group-name">
                                ${g.group_name || '群' + g.group_id}
                                <span class="switch-group-id" style="color:${statusColor}">${statusText}</span>
                            </div>
                            <div class="switch-group-stats">
                                <span>📝 ${msgText}</span>
                                ${daysText ? `<span>📅 ${daysText}</span>` : ''}
                                ${membersText ? `<span>👥 ${membersText}</span>` : ''}
                            </div>
                        </div>
                    </div>
                    <div class="switch-right">
                        <div class="switch-toggle ${activeClass}" onclick="toggleGroupMonitor(${g.group_id}, this)" title="点击切换监控状态"></div>
                    </div>
                </div>
            `;
        }
        container.innerHTML = html;
    } catch(e) {
        container.innerHTML = '<div style="color:#ff4d4f;font-size:13px">加载失败</div>';
    }
}

async function toggleGroupMonitor(groupId, toggleEl) {
    const isActive = toggleEl.classList.contains('active');
    const newState = !isActive;
    
    // 立即更新UI
    if (newState) {
        toggleEl.classList.add('active');
    } else {
        toggleEl.classList.remove('active');
    }
    
    try {
        // 获取当前配置
        const configData = await api('/api/system/config');
        let monitorGroups = configData.monitor_groups || [];
        
        if (newState) {
            // 开启监控：添加到列表
            if (!monitorGroups.includes(groupId)) {
                monitorGroups.push(groupId);
            }
        } else {
            // 关闭监控：从列表移除
            monitorGroups = monitorGroups.filter(g => g !== groupId);
        }
        
        if (monitorGroups.length === 0) {
            alert('至少需要保留一个监控群！');
            // 回滚UI
            if (isActive) {
                toggleEl.classList.add('active');
            } else {
                toggleEl.classList.remove('active');
            }
            return;
        }
        
        // 保存配置
        const result = await api('/api/system/config', {
            method: 'POST',
            body: JSON.stringify({
                monitor_groups: monitorGroups,
                qq_alert_enabled: configData.qq_alert_enabled,
                qq_recipients: configData.qq_recipients,
                export_dir: configData.export_dir
            })
        });
        
        if (!result.success) {
            alert('操作失败：' + (result.error || '未知错误'));
            // 回滚UI
            if (isActive) {
                toggleEl.classList.add('active');
            } else {
                toggleEl.classList.remove('active');
            }
        } else {
            // 更新状态文字
            const row = toggleEl.closest('.switch-row');
            const statusSpan = row.querySelector('.switch-group-id');
            statusSpan.textContent = newState ? '监控中' : '已暂停';
        }
    } catch(e) {
        alert('操作失败：' + e.message);
        // 回滚UI
        if (isActive) {
            toggleEl.classList.add('active');
        } else {
            toggleEl.classList.remove('active');
        }
    }
}

async function addMonitorGroup() {
    const input = document.getElementById('newGroupInput');
    const groupId = parseInt(input.value.trim());
    
    if (!groupId || isNaN(groupId)) {
        alert('请输入正确的群号！');
        return;
    }
    
    try {
        // 获取当前配置
        const configData = await api('/api/system/config');
        let monitorGroups = configData.monitor_groups || [];
        
        if (monitorGroups.includes(groupId)) {
            alert('该群已在监控列表中！');
            return;
        }
        
        monitorGroups.push(groupId);
        
        // 保存配置
        const result = await api('/api/system/config', {
            method: 'POST',
            body: JSON.stringify({
                monitor_groups: monitorGroups,
                qq_alert_enabled: configData.qq_alert_enabled,
                qq_recipients: configData.qq_recipients,
                export_dir: configData.export_dir
            })
        });
        
        if (!result.success) {
            alert('添加失败：' + (result.error || '未知错误'));
            return;
        }
        
        input.value = '';
        loadGroupSwitchList();
    } catch(e) {
        alert('添加失败：' + e.message);
    }
}

async function removeMonitorGroup(groupId) {
    if (!confirm(`确定要从监控列表中移除群 ${groupId} 吗？\n\n移除后不再接收该群的新消息，但已保存的历史记录会保留。`)) {
        return;
    }
    
    try {
        // 获取当前配置
        const configData = await api('/api/system/config');
        let monitorGroups = configData.monitor_groups || [];
        
        if (monitorGroups.length <= 1) {
            alert('至少需要保留一个监控群！');
            return;
        }
        
        monitorGroups = monitorGroups.filter(g => g !== groupId);
        
        // 保存配置
        const result = await api('/api/system/config', {
            method: 'POST',
            body: JSON.stringify({
                monitor_groups: monitorGroups,
                qq_alert_enabled: configData.qq_alert_enabled,
                qq_recipients: configData.qq_recipients,
                export_dir: configData.export_dir
            })
        });
        
        if (!result.success) {
            alert('移除失败：' + (result.error || '未知错误'));
            return;
        }
        
        loadGroupSwitchList();
    } catch(e) {
        alert('移除失败：' + e.message);
    }
}

async function restartSystem() {
    if (!confirm('确定要重启整个监控系统吗？\n\n重启后所有连接和服务都会重新初始化，大约需要10-20秒。')) {
        return;
    }
    
    const btn = event.target;
    const originalText = btn.innerHTML;
    btn.disabled = true;
    btn.innerHTML = '重启中...';
    
    try {
        const result = await api('/api/system/restart', { method: 'POST' });
        if (result.success) {
            // 显示倒计时
            let count = 15;
            btn.innerHTML = `重启中... ${count}秒后刷新`;
            
            const timer = setInterval(() => {
                count--;
                btn.innerHTML = `重启中... ${count}秒后刷新`;
                if (count <= 0) {
                    clearInterval(timer);
                    location.reload();
                }
            }, 1000);
        } else {
            alert('重启失败：' + (result.error || '未知错误'));
            btn.disabled = false;
            btn.innerHTML = originalText;
        }
    } catch(e) {
        // 可能因为进程退出导致连接断开，也算成功
        let count = 15;
        btn.innerHTML = `重启中... ${count}秒后刷新`;
        
        const timer = setInterval(() => {
            count--;
            btn.innerHTML = `重启中... ${count}秒后刷新`;
            if (count <= 0) {
                clearInterval(timer);
                location.reload();
            }
        }, 1000);
    }
}

async function saveSystemConfig() {
    const resultEl = document.getElementById('systemConfigResult');
    
    // 先获取当前配置中的监控群列表（监控群通过开关单独管理）
    const currentConfig = await api('/api/system/config');
    const monitorGroups = currentConfig.monitor_groups || [];
    
    const payload = {
        monitor_groups: monitorGroups,
        qq_alert_enabled: document.getElementById('configQQAlertEnabled').checked,
        qq_recipients: parseIdList(document.getElementById('configQQRecipients').value),
        export_dir: document.getElementById('configExportDir').value.trim()
    };
    const result = await api('/api/system/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    if (result.success) {
        resultEl.innerHTML = '<span style="color:#52c41a">已保存并立即生效</span>';
        loadDashboard();
        loadGroupFilters();
    } else {
        resultEl.innerHTML = '<span style="color:#ff4d4f">保存失败：' + (result.error || result.message || '').replace(/</g,'&lt;') + '</span>';
    }
}

async function openFolderPicker(path = '') {
    document.getElementById('folderPicker').style.display = 'block';
    const result = await api('/api/folders' + (path ? ('?path=' + encodeURIComponent(path)) : ''));
    const currentEl = document.getElementById('folderCurrent');
    const listEl = document.getElementById('folderList');
    if (result.error) {
        currentEl.textContent = '读取目录失败：' + result.error;
        listEl.innerHTML = '';
        return;
    }
    currentEl.textContent = result.current ? ('当前目录：' + result.current) : '请选择磁盘或目录';
    let html = '';
    if (result.parent) {
        html += `<div style="padding:6px"><button class="btn-secondary" onclick="openFolderPicker('${String(result.parent).replace(/\\/g,'\\\\').replace(/'/g,"\\'")}')">上一级</button></div>`;
    }
    if (result.current) {
        html += `<div style="padding:6px"><button class="btn-primary" onclick="selectExportFolder('${String(result.current).replace(/\\/g,'\\\\').replace(/'/g,"\\'")}')">使用当前目录</button></div>`;
    }
    result.dirs.forEach(d => {
        const safePath = String(d.path).replace(/\\/g,'\\\\').replace(/'/g,"\\'");
        html += `<div style="padding:6px;border-bottom:1px solid #eee;display:flex;justify-content:space-between;gap:8px">
            <span>${String(d.name).replace(/</g,'&lt;')}</span>
            <span>
                <button class="btn-secondary" onclick="openFolderPicker('${safePath}')">打开</button>
                <button class="btn-primary" onclick="selectExportFolder('${safePath}')">选择</button>
            </span>
        </div>`;
    });
    listEl.innerHTML = html || '<div class="empty">没有可访问的子目录</div>';
}

function selectExportFolder(path) {
    document.getElementById('configExportDir').value = path;
    closeFolderPicker();
}

function closeFolderPicker() {
    document.getElementById('folderPicker').style.display = 'none';
}

async function syncExportNow() {
    const resultEl = document.getElementById('systemConfigResult');
    resultEl.innerHTML = '<span style="color:#999">正在同步保存聊天记录...</span>';
    await saveSystemConfig();
    const result = await api('/api/export/sync', {method: 'POST'});
    if (result.success) {
        resultEl.innerHTML = '<span style="color:#52c41a">同步完成：已导出 ' + result.exported + ' 条聊天记录</span>';
    } else {
        resultEl.innerHTML = '<span style="color:#ff4d4f">同步失败：' + (result.error || '').replace(/</g,'&lt;') + '</span>';
    }
}

async function transferExportDir() {
    const resultEl = document.getElementById('systemConfigResult');
    const target = document.getElementById('configExportDir').value.trim();
    if (!target) {
        resultEl.innerHTML = '<span style="color:#ff4d4f">请先选择或填写新的聊天记录TXT目录</span>';
        return;
    }
    if (!confirm('确定要把已有聊天记录TXT文件转移到新目录吗？')) return;
    resultEl.innerHTML = '<span style="color:#999">正在转移聊天记录目录...</span>';
    const result = await api('/api/export/transfer', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({target_dir: target})
    });
    if (result.success) {
        document.getElementById('configExportDir').value = result.export_dir || target;
        resultEl.innerHTML = '<span style="color:#52c41a">转移完成：移动 ' + result.moved + ' 项，当前目录已更新</span>';
    } else {
        resultEl.innerHTML = '<span style="color:#ff4d4f">转移失败：' + (result.error || '').replace(/</g,'&lt;') + '</span>';
    }
}

async function loadPendingFiles() {
    const panel = document.getElementById('pendingFilesPanel');
    const list = document.getElementById('pendingFilesList');
    panel.style.display = 'block';
    list.innerHTML = '<div style="color:#999">正在加载...</div>';
    const files = await api('/api/pending-files');
    if (!files || files.length === 0) {
        list.innerHTML = '<div class="empty">暂无待确认大文件</div>';
        return;
    }
    list.innerHTML = files.map(f => {
        const msg = f.message || {};
        const safeId = String(f.file_id).replace(/'/g, "\\'");
        return `<div style="padding:8px;border-bottom:1px solid #eee">
            <div><strong>${String(f.name || '文件').replace(/</g,'&lt;')}</strong> <span style="color:#999">(${f.size_text || ''})</span></div>
            <div class="help-text">文件ID：${f.file_id} · 状态：${f.status} · 群${msg.group_id || ''} · QQ:${msg.user_id || ''} · ${msg.datetime || ''}</div>
            <div style="margin-top:6px">
                <button class="btn-primary" onclick="confirmPendingFile('${safeId}')">确认保存</button>
                <button class="btn-secondary" onclick="rejectPendingFile('${safeId}')">拒绝保存</button>
            </div>
        </div>`;
    }).join('');
}

async function confirmPendingFile(fileId) {
    const resultEl = document.getElementById('systemConfigResult');
    resultEl.innerHTML = '<span style="color:#999">正在保存大文件...</span>';
    const result = await api('/api/pending-files/' + encodeURIComponent(fileId) + '/confirm', {method: 'POST'});
    resultEl.innerHTML = result.success
        ? '<span style="color:#52c41a">大文件已保存</span>'
        : '<span style="color:#ff4d4f">保存失败：' + (result.error || '').replace(/</g,'&lt;') + '</span>';
    loadPendingFiles();
}

async function rejectPendingFile(fileId) {
    const result = await api('/api/pending-files/' + encodeURIComponent(fileId) + '/reject', {method: 'POST'});
    document.getElementById('systemConfigResult').innerHTML = result.success
        ? '<span style="color:#52c41a">已拒绝保存</span>'
        : '<span style="color:#ff4d4f">操作失败：' + (result.error || '').replace(/</g,'&lt;') + '</span>';
    loadPendingFiles();
}

async function cleanupStorage() {
    const resultEl = document.getElementById('systemConfigResult');
    resultEl.innerHTML = '<span style="color:#999">正在清理和压缩旧存储...</span>';
    const result = await api('/api/storage/cleanup', {method: 'POST'});
    if (result.error) {
        resultEl.innerHTML = '<span style="color:#ff4d4f">清理失败：' + result.error.replace(/</g,'&lt;') + '</span>';
        return;
    }
    resultEl.innerHTML = '<span style="color:#52c41a">清理完成：压缩 '
        + (result.compressed || 0) + ' 个，删除 '
        + (result.deleted || 0) + ' 个，释放 '
        + (result.freed_mb || 0) + ' MB</span>';
    loadDashboard();
}

async function loadAttachmentStats() {
    const el = document.getElementById('attachmentStats');
    el.innerHTML = '<span style="color:#999">统计中...</span>';
    const data = await api('/api/storage/attachments');
    if (data.error) {
        el.innerHTML = '<span style="color:#ff4d4f">' + data.error + '</span>';
        return;
    }
    if (!data.groups || data.groups.length === 0) {
        el.innerHTML = '暂无附件';
        return;
    }
    let html = '附件合计 <strong>' + (data.total_mb || 0) + ' MB</strong>，共 '
        + (data.total_files || 0) + ' 个文件（配额 ' + (data.max_storage_mb || 0) + ' MB）<br>';
    data.groups.forEach(g => {
        const cats = Object.keys(g.categories || {}).map(
            c => c + ' ' + g.categories[c].mb + 'MB/' + g.categories[c].files + '个'
        ).join('，');
        html += '　群 ' + g.group_id + '：<strong>' + g.mb + ' MB</strong>，' + g.files
            + ' 个文件，日期 ' + (g.oldest_date || '?') + ' ~ ' + (g.newest_date || '?')
            + '<br>　　类别：' + (cats || '无') + '<br>';
    });
    el.innerHTML = html;
}

async function cleanupAttachments(dryRun) {
    const el = document.getElementById('attachmentResult');
    const days = parseInt(document.getElementById('attachDays').value);
    if (isNaN(days) || days < 0) {
        el.innerHTML = '<span style="color:#ff4d4f">请填写有效的天数</span>';
        return;
    }
    if (!dryRun && !confirm('确定要删除 ' + days + ' 天前的附件吗？删除后无法恢复（聊天记录 JSON 不受影响）。')) {
        return;
    }
    el.innerHTML = '<span style="color:#999">' + (dryRun ? '统计中...' : '删除中...') + '</span>';
    const data = await api('/api/storage/attachments/cleanup', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({older_than_days: days, dry_run: dryRun, confirm: !dryRun})
    });
    if (!data.success) {
        el.innerHTML = '<span style="color:#ff4d4f">' + (data.error || '操作失败') + '</span>';
        return;
    }
    const r = data.result;
    const verb = dryRun ? '将要删除' : '已删除';
    let msg = '<span style="color:' + (dryRun ? '#fa8c16' : '#52c41a') + '">'
        + verb + ' ' + r.dirs + ' 个日期目录 / ' + r.files + ' 个文件，合计 ' + r.mb + ' MB</span>';
    if (r.errors && r.errors.length) {
        msg += '<br><span style="color:#ff4d4f">有 ' + r.errors.length + ' 个目录处理失败</span>';
    }
    if (dryRun) {
        msg += '<br><span style="color:#888">确认无误后点击「确认删除」</span>';
    }
    el.innerHTML = msg;
    if (!dryRun) {
        loadAttachmentStats();
    }
}

async function saveAIConfig() {
    const payload = {
        enabled: document.getElementById('aiEnabled').checked,
        api_base: document.getElementById('aiApiBase').value.trim(),
        api_key: document.getElementById('aiApiKey').value.trim(),
        model: document.getElementById('aiModel').value.trim(),
        review_interval: parseInt(document.getElementById('aiInterval').value) || 5,
        context_before_messages: parseInt(document.getElementById('aiContextBefore').value) || 0,
        context_after_messages: parseInt(document.getElementById('aiContextAfter').value) || 0,
        system_prompt: document.getElementById('aiPrompt').value.trim(),
        history_review_enabled: document.getElementById('aiHistoryReviewEnabled').checked,
        history_review_interval_hours: parseInt(document.getElementById('aiHistoryInterval').value) || 2,
        history_review_hours_back: parseInt(document.getElementById('aiHistoryHoursBack').value) || 4,
        history_review_max_messages: parseInt(document.getElementById('aiHistoryMaxMessages').value) || 150
    };
    const result = await api('/api/ai/config', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    });
    const el = document.getElementById('aiTestResult');
    if (result.success) {
        el.innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">' + result.message + '</div>';
    } else {
        el.innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">' + result.message + '</div>';
    }
}

async function testAIConnection() {
    const el = document.getElementById('aiTestResult');
    el.innerHTML = '<div style="padding:10px;color:#999">正在测试连接...</div>';
    // 先保存再测试
    await saveAIConfig();
    const result = await api('/api/ai/test', {method: 'POST'});
    if (result.success) {
        el.innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">连接成功! 模型回复: ' + (result.response || '').replace(/</g,'&lt;') + '</div>';
    } else {
        el.innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">连接失败: ' + (result.error || '').replace(/</g,'&lt;') + '</div>';
    }
}

async function runAIReviewNow() {
    const el = document.getElementById('aiTestResult');
    el.innerHTML = '<div style="padding:10px;color:#999">正在执行AI审查...</div>';
    const result = await api('/api/ai/review', {method: 'POST'});
    if (result.success) {
        el.innerHTML = '<div style="padding:10px;background:#f6ffed;border:1px solid #b7eb8f;border-radius:6px;color:#52c41a">'
            + '审查完成：审查 ' + result.reviewed_count + ' 条，发现 ' + result.violation_count + ' 条违规，剩余待审查 ' + result.pending_count + ' 条。'
            + '</div>';
        loadDashboard();
    } else {
        el.innerHTML = '<div style="padding:10px;background:#fff2f0;border:1px solid #ffccc7;border-radius:6px;color:#ff4d4f">审查失败: '
            + (result.error || result.message || '').replace(/</g,'&lt;')
            + '</div>';
    }
}

function toggleAI() {
    // 仅切换checkbox状态，不立即保存
}
</script>
</body>
</html>
"""


class WebPanel:
    """QQ bot stack component."""

    def __init__(self, store: MessageStore, host: str = "0.0.0.0",
                 port: int = 8080, debug: bool = False,
                 access_token: str = ""):
        self.store = store
        self.host = host
        self.port = port
        self.debug = debug
        
        self.access_token = (access_token or "").strip()

        self._app = Flask(__name__, template_folder="../templates")
        self._app.config['JSON_AS_ASCII'] = False
        CORS(self._app)
        if self.access_token:
            logger.warning("Web面板访问令牌已启用：请用 http://<host>:<port>/?token=你的令牌 打开面板")
        elif host not in ("127.0.0.1", "localhost"):
            logger.warning(
                f"Web面板未设置访问令牌且监听 {host}，局域网内任何人都能读取聊天记录并修改配置；"
                f"建议在 config.json 的 web_panel.access_token 里设置一个令牌"
            )

        
        self._onebot_client = None
        self._compliance_manager = None
        self._alert_manager = None
        self._exporter = None
        self._monitor = None
        
        self._backfill_state: Dict[str, Any] = {
            'running': False, 'error': '', 'current': '',
            'groups_total': 0, 'done_groups': 0, 'pages': 0,
            'scanned': 0, 'added': 0, 'self_added': 0,
            'started_at': '', 'finished_at': '',
        }

        self._register_routes()

    def set_components(self, onebot_client=None, compliance_manager=None,
                       alert_manager=None, exporter=None, companion=None,
                       word_exporter=None, monitor=None, memory_keeper=None,
                       diary_keeper=None):
        """QQ bot stack component."""
        if onebot_client is not None:
            self._onebot_client = onebot_client
        if compliance_manager is not None:
            self._compliance_manager = compliance_manager
        if alert_manager is not None:
            self._alert_manager = alert_manager
        if exporter is not None:
            self._exporter = exporter
        if companion is not None:
            self._companion = companion
        if word_exporter is not None:
            self._word_exporter = word_exporter
        if monitor is not None:
            
            self._monitor = monitor
        if memory_keeper is not None:
            self._memory_keeper = memory_keeper
            self._register_memory_routes()
        if diary_keeper is not None:
            
            from .diary_keeper import register_diary_routes
            register_diary_routes(self, diary_keeper)

    def _register_memory_routes(self):
        """QQ bot stack component."""
        if getattr(self, "_memory_routes_done", False):
            return
        self._memory_routes_done = True
        mk = self._memory_keeper

        @self._app.route('/memory')
        def memory_page():
            page = """<!DOCTYPE html>
<html lang="zh"><head><meta charset="utf-8">
<title>长期记忆管家</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
body{font-family:system-ui,-apple-system,"Microsoft YaHei",sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:20px}
h1{font-size:20px;margin:0 0 12px}
.bar{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:14px}
select,input,button{background:#1e293b;color:#e2e8f0;border:1px solid #334155;border-radius:6px;padding:6px 10px;font-size:13px}
button{cursor:pointer}button:hover{background:#334155}
.stats{font-size:12px;color:#94a3b8;margin-bottom:10px}
table{width:100%;border-collapse:collapse;font-size:13px}
th,td{padding:7px 9px;border-bottom:1px solid #1e293b;text-align:left;vertical-align:top}
th{color:#94a3b8;font-weight:500;position:sticky;top:0;background:#0f172a}
.tag{display:inline-block;padding:1px 7px;border-radius:10px;font-size:11px;margin-right:4px}
.agreement{background:#7c2d12}.trivia{background:#1e3a5f}.nickname{background:#3b0764}.affection{background:#701a37}
.done{color:#64748b}.active{color:#34d399}
small{color:#64748b}
</style></head><body>
<h1>🧠 长期记忆管家 <small>按人和时间查助手记住的每件事</small></h1>
<div class="stats" id="stats"></div>
<div class="bar">
 <select id="person"><option value="">所有人</option></select>
 <select id="cat"><option value="">全部类型</option><option value="agreement">约定</option><option value="trivia">琐事</option><option value="nickname">称呼</option><option value="affection">好感事件</option></select>
 <select id="status"><option value="">全部状态</option><option value="active">待处理</option><option value="done">已完成</option></select>
 <input id="from" type="date" title="起始日期"><input id="to" type="date" title="结束日期">
 <button onclick="load()">查询</button>
 <button onclick="delSel()">删除选中</button>
</div>
<table><thead><tr><th style="width:26px"></th><th>人</th><th>类型</th><th>内容</th><th>到期</th><th>状态</th><th>记录时间</th><th>群</th></tr></thead>
<tbody id="rows"></tbody></table>
<script>
const CAT={agreement:'约定',trivia:'琐事',nickname:'称呼',affection:'好感'};
const GID={};
async function load(){
 const p=document.getElementById('person').value, c=document.getElementById('cat').value,
 s=document.getElementById('status').value, f=document.getElementById('from').value, t=document.getElementById('to').value;
 const q=new URLSearchParams(); if(p)q.set('person_id',p); if(c)q.set('category',c); if(s)q.set('status',s); if(f)q.set('date_from',f); if(t)q.set('date_to',t);
 const r=await fetch('/api/memory/list?'+q); const d=await r.json();
 document.getElementById('rows').innerHTML=(d.items||[]).map(m=>
  `<tr><td><input type="checkbox" class="sel" value="${m.id}"></td><td>${m.person_name||''}<br><small>${m.person_id}</small></td>
   <td><span class="tag ${m.category}">${CAT[m.category]||m.category}</span></td><td>${m.content}</td>
   <td>${m.due_at||'-'}</td><td class="${m.status}">${m.status==='done'?'已完成':'待处理'}</td>
   <td>${m.created_at}</td><td>${GID[m.group_id]||m.group_id||''}</td></tr>`).join('')||'<tr><td colspan="8">没有记录</td></tr>';
}
async function loadPersons(){
 const r=await fetch('/api/memory/persons'); const d=await r.json();
 Object.assign(GID, d.groups||{});
 document.getElementById('person').innerHTML='<option value="">所有人</option>'+(d.persons||[]).map(p=>
  `<option value="${p.person_id}">${p.display_name||p.person_id}（好感${p.affection}/记事${p.memory_count}）</option>`).join('');
 const s=await fetch('/api/memory/stats'); const st=await s.json();
 document.getElementById('stats').textContent=`共 ${st.total} 条 / 待处理 ${st.active} / 人数 ${st.persons} / 待到期追问 ${st.pending_due} ｜ 模型 ${st.model}`;
}
async function delSel(){
 const ids=[...document.querySelectorAll('.sel:checked')].map(x=>x.value);
 if(!ids.length)return; if(!confirm('删除选中的 '+ids.length+' 条记忆？'))return;
 for(const id of ids){await fetch('/api/memory/delete',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:Number(id)})});}
 load();
}
loadPersons();load();
</script></body></html>"""
            return page

        @self._app.route('/api/memory/list')
        def api_memory_list():
            from flask import request as _req
            q = _req.args
            try:
                items = mk.list_memories(
                    person_id=q.get('person_id', ''), group_id=q.get('group_id', ''),
                    status=q.get('status', ''), category=q.get('category', ''),
                    date_from=q.get('date_from', ''), date_to=q.get('date_to', ''),
                    limit=int(q.get('limit', 100)), offset=int(q.get('offset', 0)))
                return jsonify({"ok": True, "items": items})
            except Exception as e:  
                return jsonify({"ok": False, "error": str(e), "items": []})

        @self._app.route('/api/memory/persons')
        def api_memory_persons():
            try:
                return jsonify({"ok": True, "persons": mk.list_persons()})
            except Exception as e:  
                return jsonify({"ok": False, "persons": [], "error": str(e)})

        @self._app.route('/api/memory/stats')
        def api_memory_stats():
            try:
                return jsonify(mk.stats())
            except Exception as e:  
                return jsonify({"error": str(e)})

        @self._app.route('/api/memory/add', methods=['POST'])
        def api_memory_add():
            from flask import request as _req
            d = _req.get_json(silent=True) or {}
            try:
                mid = mk.add_manual(d.get('person_id', ''), d.get('person_name', ''),
                                    d.get('group_id', ''), d.get('category', 'trivia'),
                                    d.get('content', ''), d.get('due_at'))
                return jsonify({"ok": True, "id": mid})
            except Exception as e:  
                return jsonify({"ok": False, "error": str(e)})

        @self._app.route('/api/memory/delete', methods=['POST'])
        def api_memory_delete():
            from flask import request as _req
            d = _req.get_json(silent=True) or {}
            try:
                return jsonify({"ok": mk.delete_memory(int(d.get('id', 0)))})
            except Exception as e:  
                return jsonify({"ok": False, "error": str(e)})

    def _sync_export_dir_memory(self, new_dir: str) -> None:
        """QQ bot stack component."""





        try:
            cfg = getattr(self._compliance_manager, "_config", None)
            if isinstance(cfg, dict) and new_dir:
                cfg.setdefault("storage", {})["export_dir"] = new_dir
        except Exception as e:
            logger.debug(f"同步导出目录到内存配置失败（不影响导出）: {e}")

    def _register_routes(self) -> None:
        """QQ bot stack component."""

        @self._app.before_request
        def _check_access_token():
            """QQ bot stack component."""
            token = self.access_token
            if not token:
                return None
            supplied = (
                request.headers.get("X-Access-Token")
                or request.args.get("token")
                or request.cookies.get("qqmon_token")
                or ""
            )
            if str(supplied) == token:
                return None
            if request.path == "/":
                return (
                    "<meta charset='utf-8'>"
                    "<h3>需要访问令牌</h3>"
                    "<p>请在网址后面加上 <code>?token=你的访问令牌</code>，"
                    "例如：<code>http://localhost:8080/?token=xxxxxx</code></p>"
                    "<p>令牌在 <code>config/config.json</code> 的 "
                    "<code>web_panel.access_token</code> 中配置。</p>"
                ), 401
            return jsonify({"error": "未授权：缺少或错误的访问令牌"}), 401

        @self._app.after_request
        def _remember_access_token(response):
            """QQ bot stack component."""
            token = self.access_token
            if token and request.args.get("token") == token:
                response.set_cookie(
                    "qqmon_token", token,
                    max_age=30 * 24 * 3600, httponly=True, samesite="Lax"
                )
            return response

        @self._app.route('/')
        def index():
            return render_template_string(DASHBOARD_HTML)

        @self._app.route('/api/export/all', methods=['POST'])
        def api_export_all():
            """QQ bot stack component."""






            data = request.get_json(silent=True) or {}
            new_dir = str(data.get('export_dir') or '').strip()
            if not getattr(self, '_exporter', None):
                return jsonify({'success': False, 'error': '导出器未初始化'}), 503
            try:
                if new_dir:
                    self._exporter.update_export_dir(new_dir)
                    self._sync_export_dir_memory(new_dir)
                count = self._exporter.export_history_from_store(self.store)
                logger.info(f"全量导出完成：{count} 条 → {self._exporter.export_dir}")
                return jsonify({
                    'success': True,
                    'exported': count,
                    'export_dir': self._exporter.export_dir,
                })
            except Exception as e:
                logger.error(f"全量导出失败: {e}\n{traceback.format_exc()}")
                return jsonify({'success': False, 'error': f'{type(e).__name__}: {e}'}), 500

        @self._app.route('/api/export/word', methods=['POST'])
        def api_export_word():
            """QQ bot stack component."""




            we = getattr(self, '_word_exporter', None)
            if not we:
                return jsonify({'success': False, 'error': 'Word 导出器未初始化'}), 503
            st = we.get_progress()
            if st.get('running'):
                return jsonify({'success': True, 'already_running': True,
                                'message': '已经在导出了，进度见 status'})
            data = request.get_json(silent=True) or {}
            
            new_dir = str(data.get('dir') or data.get('export_dir') or '').strip()
            if new_dir and getattr(self, '_exporter', None):
                try:
                    self._exporter.update_export_dir(new_dir)
                    self._sync_export_dir_memory(new_dir)
                except Exception as e:
                    logger.warning(f"Word 导出切换目录失败（继续用原目录）: {e}")
            
            if getattr(self, '_exporter', None) and getattr(self._exporter, 'export_dir', ''):
                we.export_dir = self._exporter.export_dir
            groups = self._parse_group_ids(data.get('groups'))
            threading.Thread(target=we.export_all, args=(self.store,),
                             kwargs={'groups': groups},
                             daemon=True, name='WordExport').start()
            return jsonify({
                'success': True, 'started': True,
                'out_dir': os.path.join(we.export_dir, 'Word'),
                'message': f"开始导出到 {os.path.join(we.export_dir, 'Word')}",
            })

        @self._app.route('/api/export/word/status')
        def api_export_word_status():
            we = getattr(self, '_word_exporter', None)
            if not we:
                return jsonify({'success': False, 'error': 'Word 导出器未初始化'}), 503
            out = {'success': True}
            out.update(we.get_progress())
            return jsonify(out)

        @self._app.route('/api/history/backfill', methods=['POST'])
        def api_history_backfill():
            """QQ bot stack component."""













            mon = self._monitor
            if not mon or not getattr(mon, 'history_fetcher', None):
                return jsonify({'success': False, 'error': '历史拉取器未初始化'}), 503
            st = self._backfill_state
            if st.get('running'):
                return jsonify({'success': True, 'already_running': True,
                                'message': '已经在补了，进度见 status'})

            data = request.get_json(silent=True) or {}
            groups = self._parse_group_ids(data.get('groups'))
            max_pages = data.get('max_pages')
            max_pages = int(max_pages) if max_pages is not None else 60   
            days = float(data.get('days') or 0)
            
            if days < 0:
                return jsonify({'success': False, 'error': 'days 不能是负数'}), 400
            if days > 3650:
                return jsonify({'success': False, 'error': 'days 最多 3650（10 年）'}), 400

            def worker():
                stop_time = time.time() - days * 86400 if days else 0
                groups_todo = groups or mon.config.napcat['monitor_groups']
                
                try:
                    mon._ensure_bot_qq()
                except Exception as e:
                    logger.debug(f"补齐前取机器人 QQ 失败（不影响补齐）: {e}")
                self._backfill_state.update({
                    'running': True, 'error': '', 'done_groups': 0,
                    'groups_total': len(groups_todo), 'pages': 0,
                    'scanned': 0, 'added': 0, 'self_added': 0,
                    'current': '', 'started_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                    'finished_at': '',
                })
                try:
                    for gid in groups_todo:
                        self._backfill_state['current'] = f'群{gid}'
                        logger.info(f"[历史补齐] 开始翻群 {gid} 的历史"
                                    f"（最多 {max_pages or '不限'} 页，每页 200 条）")

                        def _on_page(fresh, page, _gid=gid):
                            self._backfill_state['pages'] = \
                                self._backfill_state.get('pages', 0) + 1
                            self._backfill_state['current'] = f'群{_gid} 第{page}页'

                        for raw in mon.history_fetcher.iter_history(
                                group_id=gid, page_size=200,
                                max_pages=max_pages, stop_time=stop_time,
                                on_page=_on_page):
                            self._backfill_state['scanned'] += 1
                            try:
                                is_new = mon._ingest_raw_message(raw, source='手动补齐')
                            except Exception as e:
                                logger.debug(f"补齐消息入库跳过: {e}")
                                continue
                            if is_new:
                                self._backfill_state['added'] += 1
                                if mon.napcat.is_bot_message(
                                        mon.napcat._parse_message(raw)):
                                    self._backfill_state['self_added'] += 1
                        self._backfill_state['done_groups'] += 1
                    logger.info(f"[历史补齐] 完成：扫过 {self._backfill_state['scanned']} 条，"
                                f"新增 {self._backfill_state['added']} 条"
                                f"（其中自发言 {self._backfill_state['self_added']} 条）")
                except Exception as e:
                    logger.error(f"[历史补齐] 失败: {e}\n{traceback.format_exc()}")
                    self._backfill_state['error'] = f'{type(e).__name__}: {e}'
                finally:
                    self._backfill_state['running'] = False
                    self._backfill_state['current'] = ''
                    self._backfill_state['finished_at'] = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            threading.Thread(target=worker, daemon=True, name='HistoryBackfill').start()
            return jsonify({'success': True, 'started': True,
                            'groups': groups or mon.config.napcat['monitor_groups'],
                            'max_pages': max_pages,
                            'message': '开始回调历史（含机器人自己的发言）'})

        @self._app.route('/api/history/backfill/status')
        def api_history_backfill_status():
            out = {'success': True}
            out.update(dict(self._backfill_state))
            return jsonify(out)

        @self._app.route('/api/history/topup', methods=['POST'])
        def api_history_topup():
            """QQ bot stack component."""
            mon = self._monitor
            if not mon or not getattr(mon, 'history_fetcher', None):
                return jsonify({'success': False, 'error': '历史拉取器未初始化'}), 503
            try:
                result = mon._topup_once()
            except Exception as e:
                logger.error(f"手动补齐失败: {e}\n{traceback.format_exc()}")
                return jsonify({'success': False, 'error': f'{type(e).__name__}: {e}'}), 500
            return jsonify({'success': True, **result})

        @self._app.route('/api/stats')
        def api_stats():
            stats = self.store.get_statistics(fast=True)
            stats["pending_review"] = 0
            stats["ws_connected"] = False

            if self._compliance_manager:
                stats["pending_review"] = self._compliance_manager.get_pending_count()
            if self._onebot_client:
                napcat_stats = self._onebot_client.get_stats()
                stats["ws_connected"] = bool(napcat_stats.get("is_connected", False))
                
                
                stats["session_messages"] = napcat_stats.get("total_messages", 0)
                stats["filtered_messages"] = napcat_stats.get("filtered_messages", 0)
                stats["last_message_time"] = napcat_stats.get("last_message_time")
                stats["self_messages"] = napcat_stats.get("self_messages", 0)

            
            mon = self._monitor
            if mon is not None:
                try:
                    with mon._topup_lock:
                        stats["history_topup"] = dict(mon._topup_state)
                    stats["history_topup"]["interval"] = int(
                        mon.config.storage.get('history_topup_interval', 180) or 0)
                    stats["history_topup"]["fetch_max"] = int(
                        mon.config.storage.get('history_fetch_max', 4000) or 0)
                except Exception as e:
                    logger.debug(f"读补齐状态失败: {e}")
            stats["backfill"] = dict(self._backfill_state)

            if self._alert_manager:
                stats["alert_stats"] = self._alert_manager.get_stats()

            return jsonify(stats)

        @self._app.route('/api/messages')
        def api_messages():
            group_id = request.args.get('group_id', type=int)
            user_id = request.args.get('user_id', type=int)
            keyword = request.args.get('keyword', '')
            start_time = request.args.get('start_time', '')
            end_time = request.args.get('end_time', '')
            page = request.args.get('page', 1, type=int)
            page_size = request.args.get('page_size', 50, type=int)
            
            page = max(1, page or 1)
            page_size = max(1, min(page_size or 50, 500))
            include_alerts = request.args.get('include_alerts', '0') in ('1', 'true', 'yes')
            only_violations = request.args.get('only_violations', '0') in ('1', 'true', 'yes')

            result = self.store.query_messages(
                group_id=group_id,
                user_id=user_id,
                keyword=keyword,
                start_time=start_time,
                end_time=end_time,
                page=page,
                page_size=page_size,
                include_alerts=include_alerts,
                only_violations=only_violations
            )
            return jsonify(result)

        @self._app.route('/api/messages/file')
        def api_messages_file():
            """QQ bot stack component."""
            group_id = request.args.get('group_id', type=int)
            date = request.args.get('date', '')
            user_id = request.args.get('user_id', type=int)
            keyword = request.args.get('keyword', '')

            if not group_id or not date:
                return jsonify({"error": "缺少group_id或date参数"}), 400
            
            
            
            
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(date)):
                return jsonify({"error": "date 格式必须是 YYYY-MM-DD"}), 400
            if keyword and len(str(keyword)) > 200:
                return jsonify({"error": "keyword 太长了（上限 200 字符）"}), 400

            messages = self.store.query_from_file(
                group_id=group_id,
                date=date,
                user_id=user_id,
                keyword=keyword
            )
            return jsonify({"messages": messages, "total": len(messages)})

        @self._app.route('/api/alerts')
        def api_alerts():
            limit = request.args.get('limit', 50, type=int)
            limit = max(1, min(limit or 50, 1000))
            group_id = request.args.get('group_id', type=int)
            severity = request.args.get('severity', '')
            category = request.args.get('category', '')
            secondary_status = request.args.get('secondary_status', '')
            user_id = request.args.get('user_id', type=int)

            alerts = self.store.get_alerts(
                limit=limit,
                group_id=group_id,
                severity=severity,
                category=category,
                secondary_status=secondary_status,
                user_id=user_id
            )
            return jsonify(alerts)

        @self._app.route('/api/alerts/<alert_id>/feedback', methods=['POST'])
        def api_alert_feedback(alert_id):
            """QQ bot stack component."""
            data = request.get_json(force=True)
            feedback = data.get('feedback', '')
            result = self.store.feedback_alert(alert_id, feedback)
            return jsonify(result)

        @self._app.route('/api/alerts/users')
        def api_alert_users():
            return jsonify(self.store.get_alert_users())

        @self._app.route('/api/groups')
        def api_groups():
            groups = self.store.get_monitored_groups()
            return jsonify(groups)

        @self._app.route('/api/system/config', methods=['GET'])
        def api_system_config_get():
            if not self._compliance_manager:
                return jsonify({"error": "合规管理器未初始化"}), 400

            cfg = self._compliance_manager._config
            napcat_cfg = cfg.get("napcat", {})
            qq_cfg = cfg.get("alert", {}).get("qq", {})
            storage_cfg = cfg.get("storage", {})
            
            
            live_dir = getattr(getattr(self, '_exporter', None), 'export_dir', '') or ""
            return jsonify({
                "monitor_groups": napcat_cfg.get("monitor_groups", []),
                "qq_alert_enabled": qq_cfg.get("enabled", False),
                "qq_recipients": qq_cfg.get("recipient_user_ids", []),
                "export_dir": live_dir or storage_cfg.get("export_dir", "")
            })

        @self._app.route('/api/groups/info', methods=['GET'])
        def api_groups_info():
            """QQ bot stack component."""
            import os
            
            
            monitor_groups = []
            if self._compliance_manager:
                cfg = self._compliance_manager._config
                monitor_groups = cfg.get("napcat", {}).get("monitor_groups", [])
            
            monitor_set = set(monitor_groups)
            
            
            napcat_groups = {}  
            if self._onebot_client:
                try:
                    groups = self._onebot_client.get_group_list()
                    for g in groups:
                        gid = g.get("group_id")
                        if gid:
                            napcat_groups[int(gid)] = g
                except Exception as e:
                    logger.error(f"从NapCat获取群列表失败: {e}")
            
            
            data_dir = None
            if self.store:
                data_dir = self.store.data_dir
            elif self._compliance_manager:
                data_dir = self._compliance_manager._config.get("storage", {}).get("data_dir")
            
            
            mem_counts = {}
            if self.store and hasattr(self.store, '_index'):
                for gid, msgs in self.store._index.items():
                    mem_counts[gid] = len(msgs)
            
            
            data_groups = {}  
            if data_dir and os.path.exists(data_dir):
                for entry in os.listdir(data_dir):
                    entry_path = os.path.join(data_dir, entry)
                    if not os.path.isdir(entry_path):
                        continue
                    try:
                        group_id = int(entry)
                    except ValueError:
                        continue
                    
                    jsonl_files = [f for f in os.listdir(entry_path) if f.endswith('.jsonl') or f.endswith('.jsonl.gz')]
                    data_groups[group_id] = {
                        "date_files": len(jsonl_files)
                    }
            
            
            all_group_ids = set()
            all_group_ids.update(napcat_groups.keys())
            all_group_ids.update(data_groups.keys())
            all_group_ids.update(monitor_set)
            
            groups = []
            for gid in all_group_ids:
                napcat_info = napcat_groups.get(gid, {})
                data_info = data_groups.get(gid, {})
                
                group_name = napcat_info.get("group_name", "") or f"群{gid}"
                member_count = napcat_info.get("member_count", 0) or 0
                date_files = data_info.get("date_files", 0)
                msg_count = mem_counts.get(gid, 0)
                
                
                if msg_count == 0 and date_files > 0:
                    msg_count = date_files * 500  
                
                groups.append({
                    "group_id": gid,
                    "group_name": group_name,
                    "member_count": member_count,
                    "message_count": msg_count,
                    "date_files": date_files,
                    "is_monitored": gid in monitor_set
                })
            
            
            groups.sort(key=lambda x: (0 if x["is_monitored"] else 1, -x["message_count"]))
            
            return jsonify({"groups": groups})

        @self._app.route('/api/system/config', methods=['POST'])
        def api_system_config_set():
            if not self._compliance_manager:
                return jsonify({"success": False, "error": "合规管理器未初始化"}), 400

            data = request.get_json(force=True)
            monitor_groups = self._parse_id_list(data.get("monitor_groups", []))
            qq_recipients = self._parse_id_list(data.get("qq_recipients", []))
            qq_enabled = bool(data.get("qq_alert_enabled", False))
            export_dir = str(data.get("export_dir", "") or "").strip()

            if not monitor_groups:
                return jsonify({"success": False, "error": "至少需要填写一个监控群号"}), 400

            cfg = self._compliance_manager._config
            cfg.setdefault("napcat", {})["monitor_groups"] = monitor_groups
            qq_cfg = cfg.setdefault("alert", {}).setdefault("qq", {})
            qq_cfg["enabled"] = qq_enabled
            qq_cfg["recipient_user_ids"] = qq_recipients
            if export_dir:
                export_dir = self._normalize_path(export_dir)
                cfg.setdefault("storage", {})["export_dir"] = export_dir

            if self._onebot_client:
                self._onebot_client.monitor_groups = set(monitor_groups)
                logger.info(f"Web配置已更新监控群: {monitor_groups}")

            if self._alert_manager:
                self._alert_manager.update_qq_recipients(qq_enabled, qq_recipients)
            if export_dir and self._exporter:
                self._exporter.update_export_dir(export_dir)

            self._save_runtime_config(cfg)
            return jsonify({
                "success": True,
                "monitor_groups": monitor_groups,
                "qq_alert_enabled": qq_enabled,
                "qq_recipients": qq_recipients,
                "export_dir": export_dir
            })

        @self._app.route('/api/system/restart', methods=['POST'])
        def api_system_restart():
            """QQ bot stack component."""
            import sys
            import os
            import subprocess

            logger.warning("收到重启请求，正在准备重启...")

            
            def delayed_restart():
                import time
                time.sleep(1.0)

                python = sys.executable
                script_path = os.path.abspath(sys.argv[0])
                args = sys.argv[1:]
                cwd = os.getcwd()

                
                
                
                try:
                    if self._onebot_client:
                        self._onebot_client.stop()
                except Exception as e:
                    logger.warning(f"重启前断开 WebSocket 失败（忽略）: {e}")
                try:
                    self.store.flush()
                except Exception as e:
                    logger.warning(f"重启前刷新存储失败（忽略）: {e}")

                logger.info(f"正在重启: {python} {script_path} {' '.join(args)}")
                try:
                    if os.name == 'nt':
                        subprocess.Popen(
                            [python, script_path] + args,
                            cwd=cwd,
                            creationflags=subprocess.CREATE_NEW_CONSOLE
                        )
                    else:
                        subprocess.Popen(
                            [python, script_path] + args,
                            cwd=cwd
                        )
                except Exception as e:
                    
                    logger.error(f"重启失败，当前进程继续运行: {e}")
                    return

                
                time.sleep(0.3)
                os._exit(0)

            import threading
            threading.Thread(target=delayed_restart, daemon=True).start()

            return jsonify({"success": True, "message": "系统正在重启，3秒后请刷新页面"})

        @self._app.route('/api/folders')
        def api_folders():
            """QQ bot stack component."""
            path = request.args.get("path", "").strip()
            try:
                if not path:
                    dirs = []
                    if os.name == "nt":
                        for code in range(ord("A"), ord("Z") + 1):
                            drive = f"{chr(code)}:\\"
                            if os.path.exists(drive):
                                dirs.append({"name": drive, "path": drive})
                    else:
                        dirs.append({"name": "/", "path": "/"})
                    return jsonify({"current": "", "parent": "", "dirs": dirs})

                current = self._normalize_path(path)
                if not os.path.isdir(current):
                    return jsonify({"error": "目录不存在或不可访问"}), 400

                dirs = []
                for name in sorted(os.listdir(current), key=lambda x: x.lower()):
                    full_path = os.path.join(current, name)
                    if os.path.isdir(full_path):
                        dirs.append({"name": name, "path": full_path})
                parent = os.path.dirname(current.rstrip("\\/"))
                if parent == current:
                    parent = ""
                return jsonify({"current": current, "parent": parent, "dirs": dirs})
            except Exception as e:
                return jsonify({"error": str(e)}), 400

        @self._app.route('/api/export/sync', methods=['POST'])
        def api_export_sync():
            """QQ bot stack component."""
            if not self._exporter:
                return jsonify({"success": False, "error": "聊天记录导出器未初始化"}), 400
            try:
                exported = self._exporter.export_history_from_store(self.store)
                return jsonify({"success": True, "exported": exported})
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

        @self._app.route('/api/export/transfer', methods=['POST'])
        def api_export_transfer():
            """QQ bot stack component."""
            if not self._compliance_manager:
                return jsonify({"success": False, "error": "合规管理器未初始化"}), 400
            data = request.get_json(force=True)
            target_dir = self._normalize_path(str(data.get("target_dir", "") or "").strip())
            if not target_dir:
                return jsonify({"success": False, "error": "目标目录不能为空"}), 400

            cfg = self._compliance_manager._config
            old_dir = self._normalize_path(cfg.get("storage", {}).get("export_dir", ""))
            try:
                os.makedirs(target_dir, exist_ok=True)
                moved = self._move_directory_contents(old_dir, target_dir)
                cfg.setdefault("storage", {})["export_dir"] = target_dir
                if self._exporter:
                    self._exporter.update_export_dir(target_dir)
                    self._exporter.export_history_from_store(self.store)
                self._save_runtime_config(cfg)
                return jsonify({
                    "success": True,
                    "moved": moved,
                    "old_dir": old_dir,
                    "export_dir": target_dir
                })
            except Exception as e:
                return jsonify({"success": False, "error": str(e)}), 500

        @self._app.route('/api/pending-files')
        def api_pending_files():
            """QQ bot stack component."""
            return jsonify(self.store.get_pending_files())

        @self._app.route('/api/pending-files/<file_id>/confirm', methods=['POST'])
        def api_pending_file_confirm(file_id):
            """QQ bot stack component."""
            return jsonify(self.store.confirm_pending_file(file_id))

        @self._app.route('/api/pending-files/<file_id>/reject', methods=['POST'])
        def api_pending_file_reject(file_id):
            """QQ bot stack component."""
            return jsonify(self.store.reject_pending_file(file_id))

        @self._app.route('/api/groups/<int:group_id>/dates')
        def api_group_dates(group_id):
            dates = self.store.get_available_dates(group_id)
            return jsonify(dates)

        @self._app.route('/api/storage')
        def api_storage():
            storage_info = self.store.check_storage()
            return jsonify(storage_info)

        @self._app.route('/api/storage/cleanup', methods=['POST'])
        def api_storage_cleanup():
            
            result = self.store.cleanup_old_files()
            if result.get("skipped"):
                return jsonify({
                    "success": False,
                    "skipped": True,
                    "message": "自动清理已关闭（storage.auto_cleanup_enabled=false），未删除任何记录。"
                               "如需清理请先修改配置。",
                    "result": result,
                })
            return jsonify(result)

        @self._app.route('/api/storage/attachments')
        def api_attachment_stats():
            """QQ bot stack component."""
            try:
                return jsonify(self.store.get_attachment_stats())
            except Exception as e:
                logger.error(f"统计附件占用失败: {e}")
                return jsonify({"error": f"统计失败: {e}"}), 500

        @self._app.route('/api/storage/attachments/cleanup', methods=['POST'])
        def api_attachment_cleanup():
            """QQ bot stack component."""
            data = request.get_json(force=True, silent=True) or {}
            days = data.get("older_than_days")
            if days in (None, ""):
                return jsonify({"success": False,
                                "error": "必须指定 older_than_days（清理多少天以前的附件）"}), 400
            try:
                days = int(days)
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "older_than_days 必须是整数"}), 400
            if days < 0:
                return jsonify({"success": False, "error": "older_than_days 不能为负数"}), 400

            dry_run = bool(data.get("dry_run", True))
            if not dry_run and not data.get("confirm"):
                return jsonify({"success": False,
                                "error": "真正删除需要同时传 confirm=true"}), 400

            group_id = data.get("group_id")
            try:
                group_id = int(group_id) if group_id not in (None, "") else None
            except (TypeError, ValueError):
                return jsonify({"success": False, "error": "group_id 必须是整数"}), 400

            try:
                result = self.store.cleanup_attachments(
                    older_than_days=days,
                    group_id=group_id,
                    dry_run=dry_run,
                )
                if result.get("skipped"):
                    return jsonify({"success": False, "skipped": True,
                                    "error": result.get("message", "自动清理已关闭"),
                                    "result": result})
                return jsonify({"success": True, "result": result})
            except Exception as e:
                logger.error(f"清理附件失败: {e}")
                return jsonify({"success": False, "error": str(e)}), 500

        @self._app.route('/api/test-alert', methods=['POST'])
        def api_test_alert():
            if self._alert_manager:
                self._alert_manager.send_test_alert()
                return jsonify({"status": "ok", "message": "测试告警已发送"})
            return jsonify({"error": "告警管理器未初始化"}), 400

        @self._app.route('/api/rules/reload', methods=['POST'])
        def api_rules_reload():
            if self._compliance_manager:
                self._compliance_manager.detector.reload_rules()
                return jsonify({"status": "ok", "message": "规则已重新加载"})
            return jsonify({"error": "合规管理器未初始化"}), 400

        @self._app.route('/api/images/<path:img_path>')
        def api_serve_image(img_path):
            """QQ bot stack component."""




            try:
                return send_from_directory(self.store.data_dir, img_path)
            except NotFound:
                return jsonify({"error": "图片不存在"}), 404
            except Exception as e:
                logger.warning(f"读取图片失败: {img_path}, {e}")
                return jsonify({"error": "图片读取失败"}), 400

        @self._app.route('/api/files/<path:file_path>')
        def api_serve_file(file_path):
            """QQ bot stack component."""
            try:
                return send_from_directory(self.store.data_dir, file_path, as_attachment=True)
            except NotFound:
                return jsonify({"error": "文件不存在"}), 404
            except Exception as e:
                logger.warning(f"读取附件失败: {file_path}, {e}")
                return jsonify({"error": "附件读取失败"}), 400

        @self._app.route('/api/ai/config', methods=['GET'])
        def api_ai_config_get():
            if self._compliance_manager:
                return jsonify(self._compliance_manager.get_ai_config())
            return jsonify({"error": "合规管理器未初始化"}), 400

        @self._app.route('/api/ai/config', methods=['POST'])
        def api_ai_config_set():
            if not self._compliance_manager:
                return jsonify({"error": "合规管理器未初始化"}), 400
            data = request.get_json(force=True)
            result = self._compliance_manager.update_ai_config(
                api_base=data.get('api_base'),
                api_key=data.get('api_key'),
                model=data.get('model'),
                system_prompt=data.get('system_prompt'),
                enabled=data.get('enabled'),
                review_interval=data.get('review_interval'),
                context_before_messages=data.get('context_before_messages'),
                context_after_messages=data.get('context_after_messages'),
                history_review_enabled=data.get('history_review_enabled'),
                history_review_interval_hours=data.get('history_review_interval_hours'),
                history_review_hours_back=data.get('history_review_hours_back'),
                history_review_max_messages=data.get('history_review_max_messages')
            )
            return jsonify(result)

        @self._app.route('/api/secondary-ai/config', methods=['GET'])
        def api_secondary_ai_config_get():
            if self._compliance_manager:
                return jsonify(self._compliance_manager.get_secondary_ai_config())
            return jsonify({"error": "合规管理器未初始化"}), 400

        @self._app.route('/api/secondary-ai/config', methods=['POST'])
        def api_secondary_ai_config_set():
            if not self._compliance_manager:
                return jsonify({"error": "合规管理器未初始化"}), 400
            data = request.get_json(force=True)
            result = self._compliance_manager.update_secondary_ai_config(
                enabled=data.get('enabled'),
                api_base=data.get('api_base'),
                api_key=data.get('api_key'),
                model=data.get('model'),
                system_prompt=data.get('system_prompt')
            )
            return jsonify(result)

        @self._app.route('/api/secondary-ai/test', methods=['POST'])
        def api_secondary_ai_test():
            if self._compliance_manager:
                result = self._compliance_manager.test_secondary_ai_connection()
                return jsonify(result)
            return jsonify({"error": "合规管理器未初始化"}), 400

        @self._app.route('/api/companion/config', methods=['GET'])
        def api_companion_config_get():
            companion = getattr(self, '_companion', None)
            if not companion:
                return jsonify({"enabled": False, "bot_name": "小助手", "api_base": "", "api_key": "", "model": "", "cooldown_seconds": 10, "system_prompt": ""})
            return jsonify({"enabled": True, "bot_name": companion.bot_name, "api_base": companion.api_base, "api_key": companion.api_key, "model": companion.model, "cooldown_seconds": companion.cooldown_seconds, "system_prompt": companion.system_prompt})

        @self._app.route('/api/companion/config', methods=['POST'])
        def api_companion_config_post():
            data = request.get_json(force=True)
            companion = getattr(self, '_companion', None)
            if not companion:
                return jsonify({"success": False, "error": "陪聊功能未启用，请先在config.json中设置 chat_companion.enabled=true"})
            companion.reload_config(api_base=data.get('api_base'), api_key=data.get('api_key'), model=data.get('model'), system_prompt=data.get('system_prompt'), bot_name=data.get('bot_name'), cooldown_seconds=data.get('cooldown_seconds'))
            
            if self._compliance_manager:
                self._compliance_manager._config.setdefault('chat_companion', {})
                cc = self._compliance_manager._config['chat_companion']
                
                
                
                if data.get('enabled') is not None:
                    cc['enabled'] = bool(data.get('enabled'))
                else:
                    cc.setdefault('enabled', True)
                if data.get('bot_name'):
                    cc['bot_name'] = data['bot_name']
                if data.get('api_base'):
                    cc['api_base'] = data['api_base']
                if data.get('api_key'):
                    cc['api_key'] = data['api_key']
                if data.get('model'):
                    cc['model'] = data['model']
                if data.get('system_prompt') is not None:
                    cc['system_prompt'] = data['system_prompt']
                if data.get('cooldown_seconds'):
                    cc['cooldown_seconds'] = data['cooldown_seconds']
                self._compliance_manager._save_config()
            return jsonify({"success": True})

        @self._app.route('/api/companion/test', methods=['POST'])
        def api_companion_test():
            companion = getattr(self, '_companion', None)
            if not companion:
                return jsonify({"success": False, "error": "陪聊功能未启用"})
            return jsonify(companion.test_connection())

        @self._app.route('/api/ai/test', methods=['POST'])
        def api_ai_test():
            if self._compliance_manager:
                result = self._compliance_manager.test_ai_connection()
                return jsonify(result)
            return jsonify({"error": "合规管理器未初始化"}), 400

        @self._app.route('/api/ai/review', methods=['POST'])
        def api_ai_review():
            if not self._compliance_manager:
                return jsonify({"success": False, "error": "合规管理器未初始化"}), 400
            before = self._compliance_manager.get_pending_count()
            violations = self._compliance_manager.do_ai_review()
            status = self._compliance_manager.get_ai_status()
            last_error = status.get("last_error", "")
            return jsonify({
                "success": not bool(last_error),
                "error": last_error,
                "reviewed_count": before - status.get("pending_count", 0) if not last_error else 0,
                "violation_count": len(violations),
                "pending_count": status.get("pending_count", 0),
                "status": status
            })

    @staticmethod
    def _parse_group_ids(value):
        """QQ bot stack component."""





        if not value:
            return None
        if isinstance(value, (str, int)):
            value = [value]
        out, bad = [], []
        for g in value:
            try:
                gid = int(str(g).strip())
            except (TypeError, ValueError):
                bad.append(g)
                continue
            if gid > 0 and gid not in out:
                out.append(gid)
        if bad:
            logger.warning(f"群号列表里有解析不了的项，已忽略：{bad}")
        return out or None

    def _parse_id_list(self, value) -> list:
        """QQ bot stack component."""
        if value is None:
            return []
        if isinstance(value, str):
            raw_items = value.replace("，", ",").split(",")
        elif isinstance(value, list):
            raw_items = value
        else:
            raw_items = [value]

        result = []
        for item in raw_items:
            text = str(item).strip()
            if not text:
                continue
            try:
                num = int(text)
                if num > 0 and num not in result:
                    result.append(num)
            except ValueError:
                continue
        return result

    def _normalize_path(self, path: str) -> str:
        """QQ bot stack component."""
        path = path.strip().strip('"').strip("'")
        if not path:
            return ""
        if not os.path.isabs(path):
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            path = os.path.join(base_dir, path)
        return os.path.abspath(path)

    def _move_directory_contents(self, old_dir: str, target_dir: str) -> int:
        """QQ bot stack component."""
        if not old_dir or not os.path.isdir(old_dir):
            return 0
        old_abs = os.path.abspath(old_dir)
        target_abs = os.path.abspath(target_dir)
        if old_abs.lower() == target_abs.lower():
            return 0
        if target_abs.lower().startswith(old_abs.lower() + os.sep):
            raise ValueError("目标目录不能是当前聊天记录目录的子目录")

        moved = 0
        for name in os.listdir(old_abs):
            src = os.path.join(old_abs, name)
            dst = os.path.join(target_abs, name)
            if os.path.exists(dst):
                if os.path.isdir(src) and os.path.isdir(dst):
                    moved += self._move_directory_contents(src, dst)
                    try:
                        os.rmdir(src)
                    except OSError:
                        pass
                else:
                    base, ext = os.path.splitext(name)
                    idx = 1
                    while os.path.exists(dst):
                        dst = os.path.join(target_abs, f"{base}_{idx}{ext}")
                        idx += 1
                    shutil.move(src, dst)
                    moved += 1
            else:
                shutil.move(src, dst)
                moved += 1
        return moved

    def _save_runtime_config(self, config: Dict[str, Any]) -> None:
        """QQ bot stack component."""




        config_path = config.get("_config_path", "")
        if not config_path:
            logger.warning("保存运行时配置被跳过：config 里没有 _config_path（面板上的改动没落盘）")
            return
        save_data = {k: v for k, v in config.items() if not k.startswith("_")}
        tmp_path = f"{config_path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(save_data, f, ensure_ascii=False, indent=4)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, config_path)
        logger.info("系统配置已通过Web面板保存")

    def start(self) -> None:
        """QQ bot stack component."""
        logger.info(f"Web查询面板启动: http://{self.host}:{self.port}")
        try:
            self._app.run(
                host=self.host,
                port=self.port,
                debug=self.debug,
                threaded=True,
                use_reloader=False
            )
        except OSError as e:
            
            logger.error(
                f"Web面板启动失败：端口 {self.port} 可能已被占用（{e}）。"
                f"请关闭占用的程序，或修改 config.json 里的 web_panel.port"
            )
            raise

    def start_in_thread(self) -> None:
        """QQ bot stack component."""
        import threading

        def _run():
            
            
            
            
            
            for attempt in range(1, 5):
                try:
                    self.start()
                    return
                except OSError as e:
                    if attempt >= 4:
                        logger.error(f"Web面板线程已退出，网页面板将不可用: {e}")
                        return
                    logger.warning(
                        f"Web面板第 {attempt} 次绑定 {self.port} 失败（{e}），1 秒后重试"
                        f"（多半是重启时老进程还没让出端口）")
                    time.sleep(1)
                except Exception as e:
                    
                    logger.error(f"Web面板线程已退出，网页面板将不可用: {e}")
                    return

        thread = threading.Thread(
            target=_run,
            daemon=True,
            name="WebPanel"
        )
        thread.start()
        logger.info(f"Web面板已启动，访问地址: http://localhost:{self.port}")
