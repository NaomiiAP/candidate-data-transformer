"""
FastAPI Web UI for the Multi-Source Candidate Data Transformer.

Allows users to upload multiple files, configure projections, run the
pipeline, and visually explore the results with provenance and confidence details.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import webbrowser
from pathlib import Path
from typing import Any, Optional

import uvicorn
from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse

from candidate_transformer.pipeline import run_pipeline
from candidate_transformer.projection import ProjectionConfig

logger = logging.getLogger("candidate_transformer.web_ui")

app = FastAPI(title="Candidate Data Transformer UI")

# Base HTML page with complete Single Page App (SPA) dashboard
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en" class="dark">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Candidate Data Transformer</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script>
        tailwind.config = {
            darkMode: 'class',
            theme: {
                extend: {
                    colors: {
                        darkBg: '#090d16',
                        darkCard: '#111827',
                        neonIndigo: '#6366f1',
                        neonPurple: '#a855f7',
                        neonGreen: '#10b981'
                    }
                }
            }
        }
    </script>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        body {
            font-family: 'Outfit', sans-serif;
            background-color: #090d16;
            background-image: 
                radial-gradient(at 0% 0%, rgba(99, 102, 241, 0.15) 0px, transparent 50%),
                radial-gradient(at 100% 100%, rgba(168, 85, 247, 0.15) 0px, transparent 50%);
        }
        .glass {
            background: rgba(17, 24, 39, 0.7);
            backdrop-filter: blur(12px);
            border: 1px solid rgba(255, 255, 255, 0.08);
        }
        .glass-btn {
            background: linear-gradient(135deg, #6366f1, #a855f7);
            box-shadow: 0 4px 20px rgba(99, 102, 241, 0.4);
            transition: all 0.3s ease;
        }
        .glass-btn:hover {
            box-shadow: 0 6px 24px rgba(168, 85, 247, 0.6);
            transform: translateY(-1px);
        }
        ::-webkit-scrollbar {
            width: 8px;
        }
        ::-webkit-scrollbar-track {
            background: #090d16;
        }
        ::-webkit-scrollbar-thumb {
            background: #374151;
            border-radius: 4px;
        }
        ::-webkit-scrollbar-thumb:hover {
            background: #4b5563;
        }
    </style>
</head>
<body class="text-gray-100 min-h-screen flex flex-col antialiased">

    <!-- Top Navigation Banner -->
    <header class="glass sticky top-0 z-40 border-b border-gray-800 px-6 py-4 flex items-center justify-between">
        <div class="flex items-center space-x-3">
            <div class="h-10 w-10 rounded-xl bg-gradient-to-tr from-indigo-500 to-purple-500 flex items-center justify-between p-2 shadow-lg shadow-indigo-500/20">
                <span class="text-white font-bold text-xl select-none mx-auto">C</span>
            </div>
            <div>
                <h1 class="text-lg font-bold tracking-wider bg-gradient-to-r from-indigo-400 via-purple-400 to-pink-400 bg-clip-text text-transparent">
                    CANDIDATE TRANSFORMER
                </h1>
                <p class="text-xs text-gray-400">Multi-Source Candidate Profile Pipeline</p>
            </div>
        </div>
        <div class="flex items-center space-x-4">
            <span class="px-3 py-1 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">
                Production Grade UI
            </span>
        </div>
    </header>

    <!-- Main Container -->
    <main class="flex-1 max-w-7xl w-full mx-auto p-6 grid grid-cols-1 lg:grid-cols-12 gap-6">

        <!-- Left Column: Source Uploads & Config (5 Cols) -->
        <section class="lg:col-span-5 space-y-6 flex flex-col">
            
            <!-- File Input Form -->
            <div class="glass rounded-2xl p-6 space-y-5 flex-1 flex flex-col">
                <div class="border-b border-gray-800 pb-3 flex items-center justify-between">
                    <h2 class="text-md font-semibold text-indigo-300 tracking-wider flex items-center space-x-2">
                        <span>📥</span> <span>DATA SOURCES</span>
                    </h2>
                    <span class="text-xs text-gray-500">Provide at least one source</span>
                </div>
                
                <form id="pipeline-form" class="space-y-4 flex-1 overflow-y-auto pr-1 max-h-[50vh] lg:max-h-[60vh]">
                    
                    <!-- CSV Input -->
                    <div class="space-y-1">
                        <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Recruiter CSV (Spreadsheet)</label>
                        <input type="file" id="csv_file" name="csv_file" accept=".csv" class="w-full text-sm text-gray-400 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-gray-800 file:text-gray-300 hover:file:bg-gray-700 bg-gray-900/50 rounded-lg p-1 border border-gray-800">
                    </div>

                    <!-- ATS JSON Input -->
                    <div class="space-y-1">
                        <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider">ATS Export (JSON)</label>
                        <input type="file" id="json_file" name="json_file" accept=".json" class="w-full text-sm text-gray-400 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-gray-800 file:text-gray-300 hover:file:bg-gray-700 bg-gray-900/50 rounded-lg p-1 border border-gray-800">
                    </div>

                    <!-- LinkedIn Profile Input -->
                    <div class="space-y-1">
                        <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider">LinkedIn JSON Dump</label>
                        <input type="file" id="linkedin_file" name="linkedin_file" accept=".json" class="w-full text-sm text-gray-400 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-gray-800 file:text-gray-300 hover:file:bg-gray-700 bg-gray-900/50 rounded-lg p-1 border border-gray-800">
                    </div>

                    <!-- GitHub Profile Username / Cache -->
                    <div class="grid grid-cols-2 gap-3">
                        <div class="space-y-1">
                            <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider">GitHub Username</label>
                            <input type="text" id="github_source" name="github_source" placeholder="e.g. octocat" class="w-full bg-gray-900/50 border border-gray-800 rounded-lg px-3 py-2 text-sm text-gray-100 placeholder-gray-600 focus:outline-none focus:border-indigo-500">
                        </div>
                        <div class="space-y-1">
                            <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider">GitHub Cache (JSON)</label>
                            <input type="file" id="github_file" name="github_file" accept=".json" class="w-full text-sm text-gray-500 file:mr-2 file:py-2 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-gray-800 file:text-gray-300 hover:file:bg-gray-700 bg-gray-900/50 rounded-lg p-1 border border-gray-800">
                        </div>
                    </div>

                    <!-- Resumes (PDF, DOCX, TXT) -->
                    <div class="grid grid-cols-2 gap-3">
                        <div class="space-y-1">
                            <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Resume PDF (or .txt)</label>
                            <input type="file" id="resume_pdf" name="resume_pdf" accept=".pdf,.txt" class="w-full text-sm text-gray-500 file:mr-2 file:py-2 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-gray-800 file:text-gray-300 hover:file:bg-gray-700 bg-gray-900/50 rounded-lg p-1 border border-gray-800">
                        </div>
                        <div class="space-y-1">
                            <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Resume DOCX (or .txt)</label>
                            <input type="file" id="resume_docx" name="resume_docx" accept=".docx,.txt" class="w-full text-sm text-gray-500 file:mr-2 file:py-2 file:px-3 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-gray-800 file:text-gray-300 hover:file:bg-gray-700 bg-gray-900/50 rounded-lg p-1 border border-gray-800">
                        </div>
                    </div>

                    <!-- Recruiter Notes -->
                    <div class="space-y-1">
                        <label class="block text-xs font-semibold text-gray-400 uppercase tracking-wider">Recruiter Notes (TXT)</label>
                        <input type="file" id="notes_file" name="notes_file" accept=".txt" class="w-full text-sm text-gray-400 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:text-xs file:font-semibold file:bg-gray-800 file:text-gray-300 hover:file:bg-gray-700 bg-gray-900/50 rounded-lg p-1 border border-gray-800">
                    </div>

                    <!-- Configuration Panel -->
                    <div class="pt-3 border-t border-gray-800/60 space-y-3">
                        <label class="block text-xs font-semibold text-indigo-300 uppercase tracking-wider">Output Configuration</label>
                        
                        <div class="flex items-center space-x-6">
                            <label class="flex items-center space-x-2 text-sm text-gray-300 cursor-pointer">
                                <input type="checkbox" id="include_provenance" name="include_provenance" checked class="h-4 w-4 rounded border-gray-800 bg-gray-900 text-indigo-600 focus:ring-indigo-500">
                                <span>Track Provenance</span>
                            </label>
                            <label class="flex items-center space-x-2 text-sm text-gray-300 cursor-pointer">
                                <input type="checkbox" id="include_confidence" name="include_confidence" checked class="h-4 w-4 rounded border-gray-800 bg-gray-900 text-indigo-600 focus:ring-indigo-500">
                                <span>Track Confidence</span>
                            </label>
                        </div>
                        
                        <div class="flex items-center space-x-3 text-sm">
                            <span class="text-gray-400">On Missing:</span>
                            <select id="on_missing" name="on_missing" class="bg-gray-900 border border-gray-800 text-gray-200 rounded px-2 py-1 focus:outline-none focus:border-indigo-500">
                                <option value="null">Set Null</option>
                                <option value="omit">Omit Keys</option>
                                <option value="error">Raise Error</option>
                            </select>
                        </div>
                    </div>
                </form>
                
                <button type="button" id="btn-run" class="w-full glass-btn text-white py-3 rounded-xl font-bold tracking-widest text-sm uppercase flex items-center justify-center space-x-2">
                    <span>⚡</span> <span>Run Pipeline</span>
                </button>
            </div>
        </section>

        <!-- Right Column: Process & Output Results (7 Cols) -->
        <section class="lg:col-span-7 flex flex-col space-y-6">
            
            <!-- Stage Tracker / Logging Screen -->
            <div id="logs-panel" class="glass rounded-2xl p-6 hidden space-y-3">
                <h3 class="text-sm font-semibold text-indigo-300 tracking-wider">PIPELINE EXECUTION METRICS</h3>
                <div id="logs-list" class="space-y-2 text-xs font-mono max-h-48 overflow-y-auto bg-black/40 rounded-xl p-3 border border-gray-900 text-gray-400">
                    <!-- Dynamic logs go here -->
                </div>
            </div>

            <!-- Merged Profiles / Output Display -->
            <div class="glass rounded-2xl p-6 flex-1 flex flex-col space-y-4 min-h-[50vh]">
                <div class="border-b border-gray-800 pb-3 flex items-center justify-between">
                    <h2 class="text-md font-semibold text-purple-300 tracking-wider flex items-center space-x-2">
                        <span>👤</span> <span>MERGED CANDIDATES</span>
                    </h2>
                    <div class="flex items-center space-x-3">
                        <span id="results-count" class="text-xs text-gray-500 font-mono">0 Loaded</span>
                        <button id="btn-download" class="hidden px-2 py-1 rounded bg-indigo-600 hover:bg-indigo-500 text-[10px] font-bold text-white transition-all">Download JSON</button>
                    </div>
                </div>

                <!-- Empty State -->
                <div id="results-empty" class="flex-1 flex flex-col items-center justify-center text-center space-y-2 text-gray-500">
                    <span class="text-4xl">🧬</span>
                    <p class="font-medium text-sm text-gray-400">No Fused Candidates</p>
                    <p class="text-xs text-gray-600 max-w-xs">Upload source files on the left and trigger the pipeline execution to explore unified candidate profiles.</p>
                </div>

                <!-- Fused Candidate Cards List -->
                <div id="candidates-container" class="hidden space-y-4 overflow-y-auto max-h-[65vh] pr-1">
                    <!-- Dynamic cards go here -->
                </div>
            </div>
        </section>
    </main>

    <!-- Candidate details modal -->
    <div id="details-modal" class="fixed inset-0 z-50 hidden bg-black/75 flex items-center justify-center p-4 backdrop-blur-sm">
        <div class="glass max-w-3xl w-full rounded-2xl max-h-[85vh] flex flex-col overflow-hidden shadow-2xl border border-gray-800">
            <div class="border-b border-gray-800 p-5 flex items-center justify-between">
                <div>
                    <h3 id="modal-name" class="text-xl font-bold text-gray-100">---</h3>
                    <p id="modal-headline" class="text-xs text-indigo-400">---</p>
                </div>
                <button onclick="closeModal()" class="text-gray-500 hover:text-gray-300 text-2xl font-semibold">&times;</button>
            </div>
            
            <div id="modal-body" class="p-6 overflow-y-auto space-y-6 text-sm text-gray-300">
                <!-- Dynamic detail info goes here -->
            </div>
        </div>
    </div>

    <!-- Script to execute pipeline -->
    <script>
        const btnRun = document.getElementById('btn-run');
        const form = document.getElementById('pipeline-form');
        const emptyState = document.getElementById('results-empty');
        const container = document.getElementById('candidates-container');
        const countBadge = document.getElementById('results-count');
        const logsPanel = document.getElementById('logs-panel');
        const logsList = document.getElementById('logs-list');
        const modal = document.getElementById('details-modal');

        let parsedResults = [];
        let rawResult = null;

        function appendLog(message, isHeader = false) {
            const div = document.createElement('div');
            if (isHeader) {
                div.className = 'text-indigo-400 font-semibold mt-2';
            }
            div.textContent = `[${new Date().toLocaleTimeString()}] ${message}`;
            logsList.appendChild(div);
            logsList.scrollTop = logsList.scrollHeight;
        }

        btnRun.addEventListener('click', async () => {
            const formData = new FormData();
            
            // Files
            const csv = document.getElementById('csv_file').files[0];
            const json = document.getElementById('json_file').files[0];
            const linkedin = document.getElementById('linkedin_file').files[0];
            const pdf = document.getElementById('resume_pdf').files[0];
            const docx = document.getElementById('resume_docx').files[0];
            const notes = document.getElementById('notes_file').files[0];
            const githubFile = document.getElementById('github_file').files[0];
            
            const github = document.getElementById('github_source').value.trim();
            const includeProv = document.getElementById('include_provenance').checked;
            const includeConf = document.getElementById('include_confidence').checked;
            const onMissing = document.getElementById('on_missing').value;

            if (!csv && !json && !linkedin && !pdf && !docx && !notes && !github && !githubFile) {
                alert('Please upload at least one source file or enter a GitHub username.');
                return;
            }

            if (csv) formData.append('csv_file', csv);
            if (json) formData.append('json_file', json);
            if (linkedin) formData.append('linkedin_file', linkedin);
            if (pdf) formData.append('resume_pdf', pdf);
            if (docx) formData.append('resume_docx', docx);
            if (notes) formData.append('notes_file', notes);
            if (github) formData.append('github_source', github);
            if (githubFile) formData.append('github_file', githubFile);
            
            formData.append('include_provenance', includeProv);
            formData.append('include_confidence', includeConf);
            formData.append('on_missing', onMissing);

            // Setup logs
            logsPanel.classList.remove('hidden');
            logsList.innerHTML = '';
            appendLog('Triggering Candidate Data Transformer pipeline...', true);
            appendLog('Ingesting raw input sources...');

            btnRun.disabled = true;
            btnRun.classList.add('opacity-50');

            try {
                const response = await fetch('/run', {
                    method: 'POST',
                    body: formData
                });
                
                const result = await response.json();
                
                if (result.error) {
                    appendLog(`Error: ${result.error}`, true);
                    alert(result.error);
                    btnRun.disabled = false;
                    btnRun.classList.remove('opacity-50');
                    return;
                }

                appendLog('Stage 1-3 complete: parsed and normalized records.');
                appendLog('Stage 4 complete: clusters matched via Union-Find disjoint set.');
                appendLog('Stage 5-7 complete: merged attributes, computed corroboration ratings, generated provenance.');
                appendLog('Stage 8-9 complete: projected layout and validated schemas successfully.', true);

                rawResult = result;
                if (result.candidates) {
                    parsedResults = result.candidates;
                } else if (result.candidate_id) {
                    parsedResults = [result];
                } else {
                    parsedResults = [];
                }
                renderResults(parsedResults);

                const btnDownload = document.getElementById('btn-download');
                if (parsedResults.length > 0) {
                    btnDownload.classList.remove('hidden');
                } else {
                    btnDownload.classList.add('hidden');
                }

            } catch (err) {
                appendLog(`Fatal pipeline crash: ${err.message}`, true);
                alert('Pipeline failed: ' + err.message);
            } finally {
                btnRun.disabled = false;
                btnRun.classList.remove('opacity-50');
            }
        });

        function renderResults(candidates) {
            countBadge.textContent = `${candidates.length} Profiles`;
            if (candidates.length === 0) {
                emptyState.classList.remove('hidden');
                container.classList.add('hidden');
                return;
            }

            emptyState.classList.add('hidden');
            container.classList.remove('hidden');
            container.innerHTML = '';

            candidates.forEach((cand, idx) => {
                const emailsStr = (cand.emails || []).join(', ') || 'N/A';
                const phonesStr = (cand.phones || []).join(', ') || 'N/A';
                const skillsList = cand.skills || [];
                const confPercent = cand.overall_confidence ? Math.round(cand.overall_confidence * 100) : 0;
                
                // Card UI
                const card = document.createElement('div');
                card.className = 'glass rounded-xl p-5 hover:border-indigo-500/50 cursor-pointer transition-all duration-300';
                card.onclick = () => showDetails(idx);

                card.innerHTML = `
                    <div class="flex items-start justify-between">
                        <div class="space-y-1">
                            <h3 class="font-bold text-lg text-gray-100">${cand.full_name || 'Anonymous candidate'}</h3>
                            <p class="text-xs text-indigo-400">${cand.headline || 'No headline'}</p>
                        </div>
                        <div class="flex flex-col items-end space-y-1">
                            <span class="text-xs font-semibold px-2 py-0.5 rounded-full ${
                                confPercent >= 80 ? 'bg-emerald-500/10 text-emerald-400' :
                                confPercent >= 50 ? 'bg-yellow-500/10 text-yellow-400' :
                                'bg-red-500/10 text-red-400'
                            }">
                                ${confPercent}% Confidence
                            </span>
                            <span class="text-[10px] text-gray-500 font-mono">ID: ${cand.candidate_id || 'N/A'}</span>
                        </div>
                    </div>
                    <div class="grid grid-cols-2 gap-4 mt-4 text-xs text-gray-400">
                        <div>📧 ${emailsStr}</div>
                        <div>📞 ${phonesStr}</div>
                    </div>
                    <div class="mt-3 flex flex-wrap gap-1">
                        ${skillsList.slice(0, 5).map(s => `
                            <span class="px-2 py-0.5 rounded bg-gray-800 text-[10px] text-gray-300 font-medium">${s.name || s}</span>
                        `).join('')}
                        ${skillsList.length > 5 ? `<span class="px-2 py-0.5 rounded bg-gray-800 text-[10px] text-gray-500 font-medium">+${skillsList.length - 5} more</span>` : ''}
                    </div>
                `;
                container.appendChild(card);
            });
        }

        function showDetails(index) {
            const cand = parsedResults[index];
            const provList = cand.provenance || [];
            const nameProv = provList.find(p => (p.field_name || p.field) === 'full_name');
            const winningSource = nameProv ? nameProv.source : '';

            let nameHeader = cand.full_name || 'Anonymous Candidate';
            if (winningSource) {
                nameHeader += ` <span class="ml-3 px-2 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/10 text-indigo-400 border border-indigo-500/20">${winningSource}</span>`;
            }
            document.getElementById('modal-name').innerHTML = nameHeader;
            document.getElementById('modal-headline').textContent = cand.headline || 'No Headline';

            const body = document.getElementById('modal-body');
            body.innerHTML = '';

            // Section 1: Overview
            const locationStr = cand.location ? 
                [cand.location.city, cand.location.region, cand.location.country].filter(Boolean).join(', ') : 'N/A';
            const yearsExp = cand.years_experience !== undefined && cand.years_experience !== null ? 
                `${cand.years_experience} Years` : 'Unknown';

            let overviewHtml = `
                <div class="grid grid-cols-2 gap-4 bg-gray-900/40 p-4 rounded-xl border border-gray-800">
                    <div>
                        <p class="text-[10px] uppercase font-semibold text-gray-500">Location</p>
                        <p class="text-sm font-medium text-gray-300">${locationStr}</p>
                    </div>
                    <div>
                        <p class="text-[10px] uppercase font-semibold text-gray-500">Total Experience</p>
                        <p class="text-sm font-medium text-gray-300">${yearsExp}</p>
                    </div>
                </div>
            `;
            body.innerHTML += overviewHtml;

            // Section 1.5: Confidence Breakdown
            const fieldConf = cand.field_confidence || {};
            const confKeys = Object.keys(fieldConf);
            if (confKeys.length > 0) {
                let confHtml = `
                    <div class="space-y-2">
                        <h4 class="text-xs uppercase font-bold tracking-widest text-yellow-400">Confidence Breakdown</h4>
                        <div class="grid grid-cols-2 sm:grid-cols-4 gap-2">
                            ${Object.entries(fieldConf).map(([field, val]) => {
                                let label = `${Math.round(val * 100)}%`;
                                if (val === 0) {
                                    let isEmpty = false;
                                    if (field === 'education') isEmpty = !cand.education || cand.education.length === 0;
                                    else if (field === 'experience') isEmpty = !cand.experience || cand.experience.length === 0;
                                    else if (field === 'skills') isEmpty = !cand.skills || cand.skills.length === 0;
                                    else if (field === 'location') isEmpty = !cand.location || !cand.location.city;
                                    else if (field === 'phones') isEmpty = !cand.phones || cand.phones.length === 0;
                                    else if (field === 'emails') isEmpty = !cand.emails || cand.emails.length === 0;
                                    else if (field === 'headline') isEmpty = !cand.headline;
                                    if (isEmpty) label = '0% (No Data)';
                                }
                                return `
                                    <div class="bg-gray-900/30 border border-gray-800/40 p-2.5 rounded-lg flex flex-col justify-between">
                                        <span class="text-[10px] text-gray-500 uppercase tracking-wider font-semibold">${field.replace('_', ' ')}</span>
                                        <span class="text-sm font-bold ${
                                            val >= 0.8 ? 'text-emerald-400' :
                                            val >= 0.5 ? 'text-yellow-400' :
                                            'text-red-400'
                                        } mt-1">${label}</span>
                                    </div>
                                `;
                            }).join('')}
                        </div>
                    </div>
                `;
                body.innerHTML += confHtml;
            }

            // Section 2: Experience Timeline
            const expList = cand.experience || [];
            if (expList.length > 0) {
                let expHtml = `
                    <div class="space-y-3">
                        <h4 class="text-xs uppercase font-bold tracking-widest text-indigo-400">Work Experience</h4>
                        <div class="space-y-4 border-l border-gray-800 pl-4 relative">
                            ${expList.map(e => `
                                <div class="relative">
                                    <div class="absolute -left-[21px] top-1.5 h-2 w-2 rounded-full bg-indigo-500"></div>
                                    <div class="flex items-baseline justify-between">
                                        <h5 class="font-bold text-gray-200">${e.title || 'Job Title'}</h5>
                                        <span class="text-xs text-gray-500 font-mono">${e.start || '---'} to ${e.end || '---'}</span>
                                    </div>
                                    <p class="text-xs text-purple-400 font-medium">${e.company || 'Company'}</p>
                                    <p class="text-xs text-gray-400 mt-1 italic">${e.summary || ''}</p>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                `;
                body.innerHTML += expHtml;
            }

            // Section 3: Education
            const eduList = cand.education || [];
            if (eduList.length > 0) {
                let eduHtml = `
                    <div class="space-y-3">
                        <h4 class="text-xs uppercase font-bold tracking-widest text-purple-400">Education History</h4>
                        <div class="space-y-3">
                            ${eduList.map(edu => `
                                <div class="bg-gray-900/30 p-3 rounded-lg border border-gray-800/40">
                                    <div class="flex items-center justify-between">
                                        <h5 class="font-semibold text-gray-300">${edu.institution || 'School'}</h5>
                                        <span class="text-xs text-gray-500 font-mono">${edu.end_year || '---'}</span>
                                    </div>
                                    <p class="text-xs text-gray-400 mt-0.5">${edu.degree || 'Degree'} in ${edu.field || 'Field'}</p>
                                </div>
                            `).join('')}
                        </div>
                    </div>
                `;
                body.innerHTML += eduHtml;
            }

            // Section 4: Provenance details
            if (provList.length > 0) {
                let provHtml = `
                    <div class="space-y-3 pt-2 border-t border-gray-800">
                        <h4 class="text-xs uppercase font-bold tracking-widest text-emerald-400 flex items-center space-x-1">
                            <span>🔍</span> <span>Audit Trail & Provenance</span>
                        </h4>
                        <div class="overflow-x-auto">
                            <table class="w-full text-left text-xs font-mono border-collapse text-gray-400">
                                <thead>
                                    <tr class="border-b border-gray-800 text-[10px] text-gray-500 uppercase tracking-wider">
                                        <th class="py-2">Field</th>
                                        <th class="py-2">Source</th>
                                        <th class="py-2">Original Value</th>
                                        <th class="py-2">Normalizations</th>
                                    </tr>
                                </thead>
                                <tbody class="divide-y divide-gray-800/50">
                                    ${provList.map(p => `
                                        <tr>
                                            <td class="py-2 font-semibold text-indigo-400">${p.field_name || p.field}</td>
                                            <td class="py-2"><span class="px-1.5 py-0.5 rounded bg-gray-950 text-[10px] text-purple-400 font-medium">${p.source}</span></td>
                                            <td class="py-2 max-w-[150px] truncate" title="${p.original_value}">${p.original_value !== null ? p.original_value : 'null'}</td>
                                            <td class="py-2 text-[10px] text-gray-500">${typeof p.method === 'string' ? p.method : (Array.isArray(p.normalizations_applied) ? p.normalizations_applied.join(', ') : 'None')}</td>
                                        </tr>
                                    `).join('')}
                                </tbody>
                            </table>
                        </div>
                    </div>
                `;
                body.innerHTML += provHtml;
            }

            modal.classList.remove('hidden');
        }

        const btnDownloadElement = document.getElementById('btn-download');
        btnDownloadElement.addEventListener('click', () => {
            if (!rawResult) return;
            const blob = new Blob([JSON.stringify(rawResult, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = 'merged_profiles.json';
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            URL.revokeObjectURL(url);
        });

        function closeModal() {
            modal.classList.add('hidden');
        }
    </script>
</body>
</html>
"""

@app.get("/", response_class=HTMLResponse)
def index() -> HTMLResponse:
    """Serve the single-page application dashboard."""
    return HTMLResponse(content=HTML_TEMPLATE)

@app.post("/run")
async def run_fused_pipeline(
    csv_file: Optional[UploadFile] = File(None),
    json_file: Optional[UploadFile] = File(None),
    linkedin_file: Optional[UploadFile] = File(None),
    resume_pdf: Optional[UploadFile] = File(None),
    resume_docx: Optional[UploadFile] = File(None),
    notes_file: Optional[UploadFile] = File(None),
    github_source: Optional[str] = Form(None),
    github_file: Optional[UploadFile] = File(None),
    include_provenance: bool = Form(True),
    include_confidence: bool = Form(True),
    on_missing: str = Form("null")
) -> Any:
    """Accept file uploads, run the orchestrator, and return output JSON."""
    sources: dict[str, str] = {}
    temp_files: list[str] = []

    try:
        # Write uploaded files to temp paths
        uploads = [
            ("recruiter_csv", csv_file, ".csv"),
            ("ats_json", json_file, ".json"),
            ("linkedin", linkedin_file, ".json"),
            ("resume_pdf", resume_pdf, ".pdf"),
            ("resume_docx", resume_docx, ".docx"),
            ("recruiter_notes", notes_file, ".txt"),
            ("github", github_file, ".json"),
        ]

        for name, upload, ext in uploads:
            if upload is not None and upload.filename:
                # Create a temp file
                with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
                    content = await upload.read()
                    f.write(content)
                    sources[name] = f.name
                    temp_files.append(f.name)

        if github_source and github_source.strip():
            sources["github"] = github_source.strip()

        if not sources:
            return {"error": "At least one input source must be provided."}

        # Build runtime projection config
        config = ProjectionConfig(
            include_provenance=include_provenance,
            include_confidence=include_confidence,
            on_missing=on_missing,
        )

        # Run pipeline
        results = run_pipeline(sources, config)
        return results

    except Exception as e:
        logger.exception("Web UI pipeline run failed.")
        return {"error": str(e)}

    finally:
        # Clean up temporary files
        for path in temp_files:
            try:
                if os.path.exists(path):
                    os.unlink(path)
            except Exception:
                pass


def start_ui(host: str = "127.0.0.1", port: int = 8000) -> None:
    """Start uvicorn server and open the web UI in the default browser."""
    import socket

    # Dynamically find an available port if the specified one is occupied
    actual_port = port
    while actual_port < port + 100:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind((host, actual_port))
                break
            except OSError:
                actual_port += 1

    url = f"http://{host}:{actual_port}"
    print(f"=============================================================")
    print(f"    Starting Candidate Data Transformer Web Interface...   ")
    print(f"    Web App running at: {url}")
    print(f"=============================================================")
    
    try:
        webbrowser.open(url)
    except Exception:
        pass
        
    uvicorn.run(app, host=host, port=actual_port, log_level="warning")
