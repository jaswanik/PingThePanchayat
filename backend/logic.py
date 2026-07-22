def detect_severity(description, issue_type):
    high_priority_keywords = ['mixed', 'contamination', 'poison', 'overflow', 'health', 'fever', 'emergency', 'toxic', 'broken pipeline']
    medium_priority_keywords = ['garbage', 'stink', 'blocked', 'delay', 'odor', 'mosquitoes']
    
    desc_lower = description.lower()
    
    # Keyword based detection
    if any(word in desc_lower for word in high_priority_keywords):
        return 'High'
    elif any(word in desc_lower for word in medium_priority_keywords):
        return 'Medium'
    
    # Issue type based detection as fallback
    if issue_type in ['Water Contamination', 'Drainage Overflow']:
        return 'High'
    
    return 'Low'

def get_recommendation(area_stats):
    recommendations = []
    
    # logic based on stats
    if area_stats['total_complaints'] > 10:
        recommendations.append("Priority area identified: High volume of complaints requires immediate administrative attention.")
    
    if area_stats['issue_distribution'].get('Water Contamination', 0) > 3:
        recommendations.append("Water safety alert: Immediate pipeline inspection and water quality testing recommended.")
    
    if area_stats['issue_distribution'].get('Sanitation', 0) > 5:
        recommendations.append("Sanitation concern: Schedule deep cleaning and evaluate waste collection frequency.")
        
    if area_stats['issue_distribution'].get('Drainage Overflow', 0) > 2:
        recommendations.append("Infrastructure warning: Drainage system clearing and maintenance required before monsoon.")

    if not recommendations:
        recommendations.append("Routine monitoring: Continue regular maintenance and community feedback collection.")
        
    return recommendations

def calculate_health_score(complaints_list):
    if not complaints_list:
        return 100, "Healthy"
    
    base_score = 100
    penalty = 0
    
    for c in complaints_list:
        if c['severity'] == 'High':
            penalty += 15
        elif c['severity'] == 'Medium':
            penalty += 10
        else:
            penalty += 5
            
        if c['status'] == 'Pending':
            penalty += 5
            
    score = max(0, base_score - penalty)
    
    if score < 60:
        risk = "Critical"
    elif score < 90:
        risk = "Moderate"
    else:
        risk = "Healthy"
        
    return score, risk
