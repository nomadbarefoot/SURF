"""
Semantic Chunking System
Intelligent content chunking based on semantic boundaries and content structure
"""

import re
from typing import List, Dict, Any, Tuple
from dataclasses import dataclass
import structlog

logger = structlog.get_logger()

@dataclass
class Chunk:
    """Content chunk with metadata"""
    content: str
    chunk_type: str
    start_index: int
    end_index: int
    confidence: float
    metadata: Dict[str, Any]

class SemanticChunker:
    """Intelligent content chunking based on semantic boundaries"""
    
    # Chunking patterns for different content types
    CHUNKING_PATTERNS = {
        "paragraph": r'\n\s*\n',
        "sentence": r'[.!?]+\s+',
        "heading": r'\n\s*#{1,6}\s+',
        "list_item": r'\n\s*[-*•]\s+',
        "code_block": r'```[\s\S]*?```',
        "quote": r'\n\s*>\s+',
        "table_row": r'\n\s*\|.*\|',
        "section": r'\n\s*#{1,3}\s+'
    }
    
    # Content type specific chunking rules
    CONTENT_TYPE_RULES = {
        "news": {
            "min_chunk_size": 100,
            "max_chunk_size": 1000,
            "preferred_boundaries": ["paragraph", "sentence"],
            "preserve_structure": True
        },
        "forum": {
            "min_chunk_size": 50,
            "max_chunk_size": 500,
            "preferred_boundaries": ["paragraph", "list_item"],
            "preserve_structure": True
        },
        "financial": {
            "min_chunk_size": 200,
            "max_chunk_size": 800,
            "preferred_boundaries": ["paragraph", "sentence"],
            "preserve_structure": True
        },
        "blog": {
            "min_chunk_size": 150,
            "max_chunk_size": 1200,
            "preferred_boundaries": ["paragraph", "heading"],
            "preserve_structure": True
        },
        "general": {
            "min_chunk_size": 100,
            "max_chunk_size": 1000,
            "preferred_boundaries": ["paragraph", "sentence"],
            "preserve_structure": False
        }
    }
    
    @staticmethod
    def chunk_content(content: str, 
                     content_type: str = "general",
                     confidence_threshold: float = 0.7) -> List[Chunk]:
        """
        Chunk content based on semantic boundaries
        
        Args:
            content: Content to chunk
            content_type: Type of content (news, forum, financial, blog, general)
            confidence_threshold: Minimum confidence for chunk acceptance
            
        Returns:
            List of Chunk objects
        """
        if not content:
            return []
        
        # Get chunking rules for content type
        rules = SemanticChunker.CONTENT_TYPE_RULES.get(content_type, 
                                                      SemanticChunker.CONTENT_TYPE_RULES["general"])
        
        # Find semantic boundaries
        boundaries = SemanticChunker._find_semantic_boundaries(content, rules)
        
        # Create chunks based on boundaries
        chunks = SemanticChunker._create_chunks(content, boundaries, rules, confidence_threshold)
        
        logger.debug("Content chunked", 
                    content_type=content_type, 
                    chunk_count=len(chunks),
                    content_length=len(content))
        
        return chunks
    
    @staticmethod
    def _find_semantic_boundaries(content: str, rules: Dict[str, Any]) -> List[Tuple[int, str, float]]:
        """Find semantic boundaries in content"""
        boundaries = []
        
        for boundary_type in rules["preferred_boundaries"]:
            pattern = SemanticChunker.CHUNKING_PATTERNS.get(boundary_type)
            if not pattern:
                continue
            
            # Find all matches
            for match in re.finditer(pattern, content, re.MULTILINE):
                start = match.start()
                boundary_type_name = boundary_type
                confidence = SemanticChunker._calculate_boundary_confidence(
                    content, start, boundary_type
                )
                boundaries.append((start, boundary_type_name, confidence))
        
        # Sort by position
        boundaries.sort(key=lambda x: x[0])
        
        return boundaries
    
    @staticmethod
    def _calculate_boundary_confidence(content: str, position: int, boundary_type: str) -> float:
        """Calculate confidence for a boundary"""
        confidence = 0.5  # Base confidence
        
        # Check context around boundary
        context_start = max(0, position - 50)
        context_end = min(len(content), position + 50)
        context = content[context_start:context_end]
        
        # Paragraph boundaries are more confident
        if boundary_type == "paragraph":
            confidence += 0.3
        
        # Sentence boundaries are moderately confident
        elif boundary_type == "sentence":
            confidence += 0.2
        
        # Heading boundaries are very confident
        elif boundary_type == "heading":
            confidence += 0.4
        
        # Check for content density around boundary
        words_before = len(content[:position].split())
        words_after = len(content[position:].split())
        
        if words_before > 10 and words_after > 10:
            confidence += 0.1
        
        # Check for structural indicators
        if re.search(r'[.!?]', context):
            confidence += 0.1
        
        return min(1.0, confidence)
    
    @staticmethod
    def _create_chunks(content: str, 
                      boundaries: List[Tuple[int, str, float]], 
                      rules: Dict[str, Any],
                      confidence_threshold: float) -> List[Chunk]:
        """Create chunks based on boundaries and rules"""
        chunks = []
        min_size = rules["min_chunk_size"]
        max_size = rules["max_chunk_size"]
        
        start = 0
        for i, (boundary_pos, boundary_type, confidence) in enumerate(boundaries):
            if confidence < confidence_threshold:
                continue
            
            # Check if chunk meets size requirements
            chunk_content = content[start:boundary_pos].strip()
            if len(chunk_content) < min_size:
                continue
            
            # Split large chunks
            if len(chunk_content) > max_size:
                sub_chunks = SemanticChunker._split_large_chunk(
                    chunk_content, start, max_size, rules
                )
                chunks.extend(sub_chunks)
            else:
                chunk = Chunk(
                    content=chunk_content,
                    chunk_type=boundary_type,
                    start_index=start,
                    end_index=boundary_pos,
                    confidence=confidence,
                    metadata={
                        "size": len(chunk_content),
                        "word_count": len(chunk_content.split()),
                        "preserve_structure": rules["preserve_structure"]
                    }
                )
                chunks.append(chunk)
            
            start = boundary_pos
        
        # Handle remaining content
        if start < len(content):
            remaining_content = content[start:].strip()
            if len(remaining_content) >= min_size:
                chunk = Chunk(
                    content=remaining_content,
                    chunk_type="remaining",
                    start_index=start,
                    end_index=len(content),
                    confidence=0.5,
                    metadata={
                        "size": len(remaining_content),
                        "word_count": len(remaining_content.split()),
                        "preserve_structure": rules["preserve_structure"]
                    }
                )
                chunks.append(chunk)
        
        return chunks
    
    @staticmethod
    def _split_large_chunk(content: str, 
                          start_index: int, 
                          max_size: int, 
                          rules: Dict[str, Any]) -> List[Chunk]:
        """Split large chunks into smaller ones"""
        chunks = []
        current_start = 0
        
        while current_start < len(content):
            # Find the best split point within max_size
            end_pos = min(current_start + max_size, len(content))
            
            # Try to find a good sentence boundary
            best_split = end_pos
            for i in range(end_pos - 1, current_start + max_size // 2, -1):
                if content[i] in '.!?':
                    best_split = i + 1
                    break
            
            chunk_content = content[current_start:best_split].strip()
            if len(chunk_content) >= rules["min_chunk_size"]:
                chunk = Chunk(
                    content=chunk_content,
                    chunk_type="split",
                    start_index=start_index + current_start,
                    end_index=start_index + best_split,
                    confidence=0.6,
                    metadata={
                        "size": len(chunk_content),
                        "word_count": len(chunk_content.split()),
                        "preserve_structure": rules["preserve_structure"],
                        "is_split": True
                    }
                )
                chunks.append(chunk)
            
            current_start = best_split
        
        return chunks
    
    @staticmethod
    def get_chunk_summary(chunks: List[Chunk]) -> Dict[str, Any]:
        """Get summary statistics for chunks"""
        if not chunks:
            return {"total_chunks": 0, "total_content_length": 0}
        
        total_length = sum(chunk.metadata.get("size", 0) for chunk in chunks)
        avg_length = total_length / len(chunks) if chunks else 0
        
        chunk_types = {}
        for chunk in chunks:
            chunk_type = chunk.chunk_type
            chunk_types[chunk_type] = chunk_types.get(chunk_type, 0) + 1
        
        return {
            "total_chunks": len(chunks),
            "total_content_length": total_length,
            "average_chunk_length": avg_length,
            "chunk_types": chunk_types,
            "confidence_scores": [chunk.confidence for chunk in chunks]
        }
