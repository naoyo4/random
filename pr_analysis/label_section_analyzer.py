#!/usr/bin/env python3
"""
Script to analyze PRs with any policy label and generate a Markdown report
of which sections are modified by each PR.
"""

import argparse
import json
import os
import re
import subprocess
from collections import defaultdict
from datetime import datetime


def run_command(command):
    """Run a shell command and return the output."""
    result = subprocess.run(command, shell=True, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Error running command: {command}")
        print(f"Error: {result.stderr}")
        return ""
    return result.stdout.strip()

def get_label_file_patterns():
    """Get mapping of labels to file patterns based on config.ts"""
    return {
        "教育": ["11_ステップ１教育", "21_ステップ２教育", "32_ステップ３教育"],
        "子育て": ["12_ステップ１子育て", "31_ステップ３子育て"],
        "行政改革": ["13_ステップ１行政改革", "22_ステップ２行政改革"],
        "産業政策": ["14_ステップ１産業", "34_ステップ３産業"],
        "科学技術": ["15_ステップ１科学技術", "33_ステップ３科学技術"],
        "デジタル民主主義": ["16_ステップ１デジタル民主主義"],
        "医療": ["17_ステップ１医療", "24_ステップ２医療"],
        "経済財政": ["23_ステップ２経済財政", "36_ステップ３経済財政"],
        "エネルギー": ["35_ステップ３エネルギー"],
        "ビジョン": ["01_チームみらいのビジョン"],
        "その他政策": ["50_国政のその他重要分野"]
    }

def get_labeled_prs(label):
    """Get all PRs with the specified label."""
    open_prs_cmd = f'gh pr list --label "{label}" --state open --json number,title,url'
    open_prs_output = run_command(open_prs_cmd)
    
    closed_prs_cmd = f'gh pr list --label "{label}" --state closed --json number,title,url'
    closed_prs_output = run_command(closed_prs_cmd)
    
    open_prs = json.loads(open_prs_output) if open_prs_output else []
    closed_prs = json.loads(closed_prs_output) if closed_prs_output else []
    
    all_prs = open_prs + closed_prs
    
    return all_prs

def extract_markdown_sections(file_path):
    """Extract markdown sections from a file with improved Japanese section handling."""
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return {}
    
    with open(file_path, encoding='utf-8') as f:
        content = f.read()
    
    print(f"Extracting sections from file with {len(content.split('\n'))} lines")
    
    headings = []
    section_content = {}
    current_section_start = None
    
    for i, line in enumerate(content.split('\n')):
        heading_match = re.match(r'^(#+)\s+(.+)$', line)
        
        jp_section_match = None
        if not heading_match:
            jp_section_match = re.match(r'^([０-９]+）|\d+）)\s*(.+)$', line)
        
        jp_policy_match = None
        if not heading_match and not jp_section_match:
            jp_policy_match = re.match(r'^###\s+(現状認識・課題分析|政策概要)$', line)
        
        if heading_match:
            level = len(heading_match.group(1))
            title = heading_match.group(2).strip()
            headings.append((i+1, level, title))
            print(f"Found heading at line {i+1}: {title} (level {level})")
            
            if current_section_start is not None:
                section_content[current_section_start] = (current_section_start, i)
            current_section_start = i+1
            
        elif jp_section_match:
            level = 2
            title = jp_section_match.group(0).strip()
            headings.append((i+1, level, title))
            print(f"Found JP section at line {i+1}: {title} (level {level})")
            
            if current_section_start is not None:
                section_content[current_section_start] = (current_section_start, i)
            current_section_start = i+1
            
        elif jp_policy_match:
            level = 3
            title = jp_policy_match.group(1).strip()
            headings.append((i+1, level, title))
            print(f"Found JP policy section at line {i+1}: {title} (level {level})")
            
            if current_section_start is not None:
                section_content[current_section_start] = (current_section_start, i)
            current_section_start = i+1
    
    if current_section_start is not None and len(content.split('\n')) > 0:
        section_content[current_section_start] = (current_section_start, len(content.split('\n')))
    
    sections = {}
    
    sorted_headings = sorted(headings, key=lambda x: x[0])
    
    for i, (line_num, level, title) in enumerate(sorted_headings):
        parent_sections = []
        current_parent_level = 0
        
        for j in range(i-1, -1, -1):
            prev_line, prev_level, prev_title = sorted_headings[j]
            
            if prev_level < level and prev_level > current_parent_level:
                parent_sections.insert(0, prev_title)
                current_parent_level = prev_level
                
                if prev_level == 1:
                    break
        
        section_path = " > ".join(parent_sections + [title])
        
        content_range = section_content.get(line_num, (line_num, line_num))
        
        sections[line_num] = {
            "level": level,
            "title": title,
            "path": section_path,
            "parent_sections": parent_sections,
            "start_line": content_range[0],
            "end_line": content_range[1]
        }
    
    return sections

def find_section_for_line(sections, line_number):
    """Find the section that contains a specific line."""
    for _section_line, section_info in sections.items():
        if section_info["start_line"] <= line_number <= section_info["end_line"]:
            return section_info
    
    section_lines = sorted(sections.keys())
    for i, section_line in enumerate(section_lines):
        if section_line > line_number:
            if i > 0:
                return sections[section_lines[i-1]]
            break
    
    if section_lines:
        return sections[section_lines[-1]]
    
    return None

def get_file_diff(pr_number, file_path):
    """Get the diff for a specific file in a PR using git commands."""
    command = f"gh pr view {pr_number} --json headRefName"
    output = run_command(command)
    try:
        data = json.loads(output)
        branch_name = data.get('headRefName')
        if not branch_name:
            print(f"Could not get branch name for PR #{pr_number}")
            return ""
        
        fetch_cmd = f"git fetch origin {branch_name}"
        run_command(fetch_cmd)
        
        diff_cmd = f"git diff main..origin/{branch_name} -- '{file_path}'"
        return run_command(diff_cmd)
    except json.JSONDecodeError:
        print(f"Error parsing JSON for PR branch: {output}")
        return ""

def extract_line_numbers_from_diff(diff_text):
    """Extract line numbers from a diff."""
    line_numbers = []
    current_line = None
    
    for line in diff_text.split('\n'):
        if line.startswith('@@'):
            match = re.search(r'@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@', line)
            if match:
                current_line = int(match.group(1))
                # Get line count but not used
        elif current_line is not None:
            if line.startswith('+') and not line.startswith('+++'):
                line_numbers.append(current_line)
                current_line += 1
            elif line.startswith('-'):
                pass
            else:
                current_line += 1
    
    return line_numbers

def get_pr_details(pr_number):
    """Get details for a specific PR."""
    cmd = f'gh pr view {pr_number} --json number,title,url,body'
    output = run_command(cmd)
    if not output:
        return None
    
    pr_data = json.loads(output)
    return pr_data

def get_pr_files(pr_number):
    """Get the files changed in a PR."""
    cmd = f'gh pr view {pr_number} --json files'
    output = run_command(cmd)
    if not output:
        return []
    
    pr_data = json.loads(output)
    return [file['path'] for file in pr_data.get('files', [])]

def analyze_pr(pr_number, label="教育"):
    """Analyze a PR and extract the sections it modifies for the given label."""
    pr_details = get_pr_details(pr_number)
    if not pr_details:
        print(f"Failed to get details for PR #{pr_number}")
        return None
    
    pr_files = get_pr_files(pr_number)
    if not pr_files:
        print(f"No files found for PR #{pr_number}")
        return None
    
    file_patterns = get_label_file_patterns().get(label, [])
    if not file_patterns:
        print(f"No file patterns found for label: {label}")
        return None
    
    label_files = [f for f in pr_files if f.endswith('.md') and 
                   any(f.startswith(pattern) for pattern in file_patterns)]
    
    if not label_files:
        print(f"No {label} files found for PR #{pr_number}")
        return None
    
    results = []
    
    for file_path in label_files:
        print(f"Processing file: {file_path}")
        full_path = os.path.join(os.getcwd(), file_path)
        
        if not os.path.exists(full_path):
            print(f"Warning: File {full_path} does not exist, skipping")
            continue
        
        file_diff = get_file_diff(pr_number, file_path)
        
        if not file_diff:
            print(f"No diff found for file {file_path}")
            continue
        
        print(f"Found diff for file {file_path}, length: {len(file_diff)}")
        
        line_numbers = extract_line_numbers_from_diff(file_diff)
        
        if not line_numbers:
            print(f"No line numbers found in diff for file {file_path}")
            continue
        
        print(f"Affected line numbers: {line_numbers[:10]}...")
        
        sections = extract_markdown_sections(full_path)
        print(f"Found {len(sections)} sections in {file_path}")
        
        if len(sections) > 0:
            print(f"Section titles: {[s['title'] for s in sections.values()][:5]}")
        
        affected_sections = set()
        for line_number in line_numbers:
            section = find_section_for_line(sections, line_number)
            if section:
                print(f"Line {line_number} is in section: {section['title']}")
                affected_sections.add((section['title'], section['path']))
        
        for section_title, section_path in affected_sections:
            results.append({
                'pr_number': pr_number,
                'pr_title': pr_details.get('title', ''),
                'pr_url': pr_details.get('url', ''),
                'file': file_path,
                'section': section_title,
                'section_path': section_path,
                'changes': [line for line in file_diff.split('\n') if line.startswith('+') and not line.startswith('+++')]
            })
    
    print(f"Found {len(results)} affected sections")
    return results

def generate_markdown_report(pr_analyses, label="教育"):
    """Generate a Markdown report from the PR analyses for the specified label."""
    if not pr_analyses:
        return f"# {label}関連PRの分析\n\n分析対象のPRが見つかりませんでした。"
    
    sections_to_prs = defaultdict(list)
    for pr in pr_analyses:
        for result in pr.get("results", []):
            section_key = f"{result['file']}: {result['section_path']}"
            sections_to_prs[section_key].append({
                "number": result['pr_number'],
                "title": result['pr_title'],
                "url": result['pr_url']
            })
    
    report = f"# {label}関連PRの分析\n\n"
    report += f"分析日時: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
    
    report += "## セクション別PR一覧\n\n"
    for section_key, prs in sections_to_prs.items():
        if len(prs) > 1:  # Only show sections with multiple PRs
            file_path, section_path = section_key.split(": ", 1)
            report += f"### {file_path}\n"
            report += f"#### {section_path}\n"
            report += "このセクションを変更するPR:\n"
            for pr in prs:
                report += f"- PR #{pr['number']}: [{pr['title']}]({pr['url']})\n"
            report += "\n"
    
    report += "## PR別変更セクション一覧\n\n"
    pr_to_sections = defaultdict(list)
    for pr in pr_analyses:
        for result in pr.get("results", []):
            pr_key = f"{result['pr_number']}:{result['pr_title']}"
            section_info = {
                'file': result['file'],
                'section_path': result['section_path']
            }
            pr_to_sections[pr_key].append(section_info)
    
    for pr_key, sections in sorted(pr_to_sections.items()):
        pr_number, pr_title = pr_key.split(":", 1)
        report += f"### PR #{pr_number}: {pr_title}\n"
        
        for section in sections:
            report += f"- {section['file']}: {section['section_path']}\n"
        
        report += "\n"
    
    return report

def main():
    parser = argparse.ArgumentParser(description="Analyze PRs with specified label")
    parser.add_argument("--label", default="教育", help="Label to analyze (default: 教育)")
    parser.add_argument("--output", help="Output file for the Markdown report")
    parser.add_argument("--limit", type=int, default=20, help="Limit the number of PRs to analyze")
    parser.add_argument("--pr", type=int, help="Analyze a specific PR number")
    parser.add_argument("--format", choices=["text", "json"], default="text", 
                        help="Output format (default: text)")
    args = parser.parse_args()
    
    if args.pr:
        print(f"Analyzing PR #{args.pr} for label {args.label}")
        results = analyze_pr(args.pr, args.label)
        if results:
            pr_analyses = [{
                "pr_number": args.pr,
                "pr_title": "Single PR Analysis",
                "pr_url": f"https://github.com/team-mirai/policy/pull/{args.pr}",
                "results": results
            }]
        else:
            pr_analyses = []
    else:
        labeled_prs = get_labeled_prs(args.label)
        print(f"Found {len(labeled_prs)} PRs with the {args.label} label")
        
        labeled_prs = labeled_prs[:args.limit]
        
        pr_analyses = []
        for pr in labeled_prs:
            pr_number = pr["number"]
            print(f"\nAnalyzing PR #{pr_number}: {pr['title']}")
            results = analyze_pr(pr_number, args.label)
            if results:
                pr_analyses.append({
                    "pr_number": pr_number,
                    "pr_title": pr['title'],
                    "pr_url": pr['url'],
                    "results": results
                })
    
    if args.format == "json":
        output = json.dumps(pr_analyses, ensure_ascii=False, indent=2)
    else:
        output = generate_markdown_report(pr_analyses, args.label)
    
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"Report written to {args.output}")
    else:
        print("\n" + "="*80 + "\n")
        print(output)

if __name__ == "__main__":
    main()
