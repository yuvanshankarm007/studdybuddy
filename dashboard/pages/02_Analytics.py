"""
StudyBuddy Analytics Page
Study patterns, progress tracking, and agent decision traces
"""
import streamlit as st
import asyncio
import concurrent.futures
from datetime import datetime, timedelta

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from src.services.dynamodb import dynamodb_service
from src.services.memory import memory_service
from src.models.schemas import StudyMode

st.set_page_config(page_title="Analytics | StudyBuddy", layout="wide")

st.title("📊 Study Analytics")
st.markdown("Track your patterns, progress, and agent insights")


def run_async(coro):
    with concurrent.futures.ThreadPoolExecutor() as pool:
        return pool.submit(asyncio.run, coro).result()


# ========== Summary Cards ==========

col1, col2, col3, col4 = st.columns(4)

try:
    profile = run_async(memory_service.get_or_create_profile("user_123"))
    streak = memory_service.get_streak("user_123")
    
    with col1:
        st.metric("📚 Total Sessions", profile.total_sessions if profile else 0)
    with col2:
        st.metric("⏱️ Total Minutes", profile.total_minutes if profile else 0)
    with col3:
        st.metric("🔥 Current Streak", streak["current_streak"])
    with col4:
        completion = f"{profile.completion_rate*100:.0f}%" if profile and profile.completion_rate else "N/A"
        st.metric("✅ Completion Rate", completion)
        
except Exception as e:
    st.warning("Could not load profile data")

st.divider()

# ========== Session History ==========

st.subheader("📈 Session History")

try:
    sessions = dynamodb_service.get_user_sessions("user_123", limit=30)
    
    if sessions:
        import pandas as pd
        
        # Prepare data
        df_data = []
        for s in sessions:
            df_data.append({
                "Date": s.get('timestamp', '')[:10],
                "Mode": s.get('mode', 'Unknown'),
                "Planned": s.get('planned_minutes', 0),
                "Actual": s.get('actual_minutes', 0),
                "Completed": "✅" if s.get('completed') else "❌",
                "Focus": s.get('focus_score', 'N/A')
            })
        
        df = pd.DataFrame(df_data)
        
        # Display table
        st.dataframe(
            df,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Date": st.column_config.DateColumn("Date"),
                "Mode": st.column_config.TextColumn("Mode"),
                "Planned": st.column_config.NumberColumn("Planned (min)"),
                "Actual": st.column_config.NumberColumn("Actual (min)"),
                "Completed": st.column_config.TextColumn("Status"),
                "Focus": st.column_config.NumberColumn("Focus")
            }
        )
        
        # Charts
        st.divider()
        st.subheader("📊 Visualizations")
        
        col_chart1, col_chart2 = st.columns(2)
        
        with col_chart1:
            st.markdown("#### Daily Study Minutes")
            
            # Aggregate by date
            df['Date'] = pd.to_datetime(df['Date'])
            daily = df.groupby('Date')['Actual'].sum().reset_index()
            
            st.line_chart(daily.set_index('Date'))
        
        with col_chart2:
            st.markdown("#### Mode Distribution")
            
            mode_counts = df['Mode'].value_counts()
            st.bar_chart(mode_counts)
        
        # Completion rate over time
        st.divider()
        st.markdown("#### Completion Trend")
        
        df['Completed_Bool'] = df['Completed'].apply(lambda x: x == "✅")
        daily_completion = df.groupby('Date')['Completed_Bool'].mean().reset_index()
        daily_completion['Completion_Rate'] = daily_completion['Completed_Bool'] * 100
        
        st.line_chart(daily_completion.set_index('Date')['Completion_Rate'])
        
    else:
        st.info("No sessions yet. Start your first session on the Home page!")
        
except Exception as e:
    st.error(f"Could not load history: {e}")


# ========== Pattern Analysis ==========

st.divider()
st.subheader("🧠 Pattern Analysis")

try:
    patterns = run_async(memory_service.analyze_patterns("user_123"))
    
    if patterns.get('status') == 'success':
        pattern_data = patterns.get('patterns', {})
        
        col_p1, col_p2 = st.columns(2)
        
        with col_p1:
            st.markdown("#### 🔍 Detected Patterns")
            
            best_mode = pattern_data.get('best_mode', 'N/A')
            best_time = pattern_data.get('best_time', 'N/A')
            energy_pattern = pattern_data.get('energy_pattern', 'N/A')
            
            st.metric("Best Mode", best_mode)
            st.metric("Best Time", best_time)
            st.metric("Energy Pattern", energy_pattern)
        
        with col_p2:
            st.markdown("#### 💡 Recommendation")
            recommendation = pattern_data.get('recommendation', 'Keep studying consistently!')
            st.info(recommendation)
        
    else:
        st.info(patterns.get('message', 'Complete more sessions to see patterns.'))
        
except Exception as e:
    st.warning("Pattern analysis unavailable")


# ========== Agent Decision Traces ==========

st.divider()
st.subheader("🔍 Agent Decision Traces")

try:
    traces = dynamodb_service.get_recent_traces("user_123", limit=10)
    
    if traces:
        for trace in traces:
            with st.expander(f"Trace: {trace.get('trace_id', 'Unknown')[:8]}..."):
                st.json({
                    "timestamp": trace.get('timestamp'),
                    "latency_ms": trace.get('latency_ms'),
                    "confidence": trace.get('confidence'),
                    "input": trace.get('input_state'),
                    "wellness": trace.get('wellness_data'),
                    "final_plan": trace.get('final_plan'),
                    "reasoning": trace.get('reasoning_chain')
                })
    else:
        st.caption("No traces available")
        
except Exception as e:
    st.caption("Traces unavailable")


# ========== Wellness Trends ==========

st.divider()
st.subheader("🏥 Wellness Trends")

try:
    from src.services.wellness_data import wellness_data_service
    
    history = run_async(wellness_data_service.get_historical_wellness("user_123", days=7))
    
    if history:
        import pandas as pd
        
        wellness_df = pd.DataFrame([
            {
                "Date": h.timestamp.strftime('%Y-%m-%d'),
                "Sleep": h.sleep_hours,
                "Quality": h.sleep_quality,
                "Stress": h.stress_level
            }
            for h in history
        ])
        
        st.line_chart(wellness_df.set_index('Date'))
    else:
        st.caption("No wellness data available")
        
except Exception as e:
    st.caption("Wellness trends unavailable")
