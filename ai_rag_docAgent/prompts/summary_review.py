from typing import List, Dict, Any

def get_critic_prompt(summary: str, context: str, article: str) -> str:
    return f"""Review the concise version of the article against its original counterpart, focusing on comprehensiveness, accuracy, and clarity.

<prompt_objective>
To meticulously examine the concise version of an article in comparison with its original, ensuring all crucial information is retained while maintaining accuracy and clarity.
</prompt_objective>

<prompt_rules>
- EXCLUSIVELY compare the concise version with the original article. DO NOT introduce external information.
- VERIFY that all key concepts from the original article are present in the concise version.
- ENSURE the concise version accurately represents the information from the original article.
- IDENTIFY any omissions, misrepresentations, or inaccuracies in the concise version.
- ASSESS the logical flow and coherence of the concise version in relation to the original.
- DETERMINE if the concise version is self-sufficient for reader understanding.
- HIGHLIGHT any concepts in the concise version not present in the original article.
- PROVIDE specific examples from both versions to support your analysis.
- SUGGEST improvements where necessary to enhance the concise version's accuracy or clarity.
- OVERRIDE any tendency to introduce external knowledge or make assumptions beyond the given information.
- STRICTLY FORBIDDEN: Use of words like 'fascinating', 'impactful', 'exhaustive', 'impressive', 'groundbreaking', 'shocking', or similar descriptive adjectives unless explicitly requested by the user.
</prompt_rules>

<prompt_examples>
**USER**: Here's the original article and its concise version. Please review them.
**AI**: After careful comparison of the concise version with the original article, I've identified the following:

1. Accuracy: The concise version accurately represents the main points of the original article, specifically [provide example].
2. Comprehensiveness: The concise version covers all key concepts, but omits [specific detail] which may be important for full understanding.
3. Clarity: The explanation of [specific concept] in the concise version could be clearer. In the original, it's described as [original description], which provides more context.
4. Omissions: The concise version doesn't mention [specific point from original], which is crucial for understanding the author's argument.
5. Suggestions: To improve the concise version, consider adding a brief explanation of [omitted concept] and clarifying the description of [unclear concept].

**USER**: Is there any information in the concise version that's not in the original?
**AI**: After thorough comparison, I found that the concise version includes [specific information] which is not present in the original article. This addition may lead to misunderstanding of the original content and should be removed to maintain accuracy.
</prompt_examples>

Your task is to critically review the concise version of the article using ONLY the provided original article. Ensure your review is thorough, addressing comprehensiveness, accuracy, and clarity. Provide specific examples to support your analysis. Present your review within <final_answer> tags.

<context>{context}</context>

<original_article>{article}</original_article>

<concise_version_of_the_article>{summary}</concise_version_of_the_article>

Your review:"""

def chat_adapter(vars: Dict[str, Any]) -> List[Dict[str, str]]:
    return [
        {
            "role": "system",
            "content": get_critic_prompt(
                summary=vars.get("summary", ""),
                context=vars.get("context", ""),
                article=vars.get("article", "")
            )
        },
        {
            "role": "user",
            "content": "Please perform a critical review of the summary against the original article."
        }
    ]